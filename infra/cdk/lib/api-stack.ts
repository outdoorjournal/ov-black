import { Stack, type StackProps, CfnOutput, Duration, RemovalPolicy } from 'aws-cdk-lib';
import { Peer, Port, SecurityGroup, SubnetType, Vpc } from 'aws-cdk-lib/aws-ec2';
import { Repository, TagStatus } from 'aws-cdk-lib/aws-ecr';
import {
  Cluster,
  ContainerImage,
  FargateService,
  FargateTaskDefinition,
  LogDriver,
  Secret as EcsSecret,
} from 'aws-cdk-lib/aws-ecs';
import {
  ApplicationLoadBalancer,
  ApplicationProtocol,
  ApplicationTargetGroup,
  ListenerAction,
  TargetType,
} from 'aws-cdk-lib/aws-elasticloadbalancingv2';
import { Effect, PolicyStatement, Role, ServicePrincipal } from 'aws-cdk-lib/aws-iam';
import { LogGroup, RetentionDays } from 'aws-cdk-lib/aws-logs';
import type { Secret as SmSecret } from 'aws-cdk-lib/aws-secretsmanager';
import type { Construct } from 'constructs';

export interface ApiStackProps extends StackProps {
  readonly envName: 'staging' | 'prod';
  readonly vpcId: string;
  readonly availabilityZones: string[];
  readonly publicSubnetIds: string[];
  readonly privateSubnetIds: string[];
  readonly supabaseServiceRoleSecret: SmSecret;
  readonly supabaseJwtSecret: SmSecret;
  readonly databaseUrlSecret: SmSecret;
  readonly bedrockAgentCoreRuntimeArnSecret: SmSecret;
  readonly agentTokenSigningSecret: SmSecret;
  /** Web app origin → WEB_ORIGIN. Empty means "not wired yet"; we skip injection then. */
  readonly webOrigin: string;
  /** Region of the Bedrock AgentCore runtime → AWS_REGION for apps/api's boto3 client. */
  readonly agentcoreRegion: string;
  /** Image tag to deploy. Defaults to `latest`; CI overrides via `-c imageTag=...`. */
  readonly imageTag?: string;
}

/**
 * apps/api on ECS Fargate behind an ALB (D002). Consumes the existing
 * NetworkStack's VPC (Control Tower: provisioned in a separate account-bound
 * repo) by ID + subnet attributes so this stack stays hermetic and synth works
 * without AWS credentials.
 *
 * Surfaces (for the slice's demo bar):
 *   - ALB DNS serving HTTP on port 80 → target group /health on container 8000
 *   - CloudWatch log group /ecs/ov-black-api with 30d retention
 *   - IAM task role scoped to GetSecretValue on exactly the two Supabase secrets
 *   - ECR repo ov-black-api for the container image
 */
export class ApiStack extends Stack {
  readonly albDnsName: string;
  readonly ecrRepositoryUri: string;
  readonly logGroupName: string;

  constructor(scope: Construct, id: string, props: ApiStackProps) {
    super(scope, id, props);

    const vpc = Vpc.fromVpcAttributes(this, 'ImportedVpc', {
      vpcId: props.vpcId,
      availabilityZones: props.availabilityZones,
      publicSubnetIds: props.publicSubnetIds,
      privateSubnetIds: props.privateSubnetIds,
    });

    // ── ECR ──────────────────────────────────────────────────────────────────
    const repository = new Repository(this, 'ApiRepository', {
      repositoryName: `ov-black-api-${props.envName}`,
      imageScanOnPush: true,
      removalPolicy: props.envName === 'prod' ? RemovalPolicy.RETAIN : RemovalPolicy.DESTROY,
      emptyOnDelete: props.envName !== 'prod',
      lifecycleRules: [
        {
          description: 'Keep the last 10 tagged images.',
          maxImageCount: 10,
          tagStatus: TagStatus.TAGGED,
          rulePriority: 1,
          tagPrefixList: ['v', 'sha-', 'latest'],
        },
        {
          description: 'Expire untagged images after 7 days.',
          maxImageAge: Duration.days(7),
          tagStatus: TagStatus.UNTAGGED,
          rulePriority: 2,
        },
      ],
    });

    // ── CloudWatch log group ─────────────────────────────────────────────────
    const logGroup = new LogGroup(this, 'ApiLogGroup', {
      logGroupName: `/ecs/ov-black-api-${props.envName}`,
      retention: RetentionDays.ONE_MONTH,
      removalPolicy: props.envName === 'prod' ? RemovalPolicy.RETAIN : RemovalPolicy.DESTROY,
    });

    // ── ECS cluster ──────────────────────────────────────────────────────────
    const cluster = new Cluster(this, 'ApiCluster', {
      vpc,
      clusterName: `ov-black-api-${props.envName}`,
    });

    // ── Task definition + container ──────────────────────────────────────────
    const taskDefinition = new FargateTaskDefinition(this, 'ApiTaskDefinition', {
      cpu: 512,
      memoryLimitMiB: 1024,
      family: `ov-black-api-${props.envName}`,
    });

    // Task role: the role the container itself assumes. Scope secretsmanager
    // reads to EXACTLY the secret ARNs we ship — no wildcard, no `*` resource.
    taskDefinition.taskRole.addToPrincipalPolicy(
      new PolicyStatement({
        effect: Effect.ALLOW,
        actions: ['secretsmanager:GetSecretValue', 'secretsmanager:DescribeSecret'],
        resources: [
          props.supabaseServiceRoleSecret.secretArn,
          props.supabaseJwtSecret.secretArn,
          props.databaseUrlSecret.secretArn,
          props.bedrockAgentCoreRuntimeArnSecret.secretArn,
          props.agentTokenSigningSecret.secretArn,
        ],
      }),
    );

    // Bedrock AgentCore invoke + memory actions. Resource is `*` because the
    // AgentCore runtime ARN is populated out-of-band by the operator after
    // console-side agent creation (see SecretsStack) — it is not known at CDK
    // synth time. R017 deliberately accepts this wildcard as an M001 concession;
    // tighten to `arn:aws:bedrock-agentcore:<region>:<account>:runtime/<runtime-id>`
    // once S05 stabilizes enough to move agent provisioning into CDK.
    taskDefinition.taskRole.addToPrincipalPolicy(
      new PolicyStatement({
        effect: Effect.ALLOW,
        actions: [
          'bedrock-agentcore:InvokeAgentRuntime',
          'bedrock-agentcore:CreateEvent',
          'bedrock-agentcore:ListEvents',
          'bedrock-agentcore:GetEvent',
        ],
        resources: ['*'],
      }),
    );
    // Execution role (ECR pull + CloudWatch write) is added automatically by
    // the FargateTaskDefinition L2 when we attach the image and log driver.

    // Image selection: when CI (or a manual deploy) passes `-c imageTag=<sha>`
    // we pull that tag from the stack's ECR repo. With no imageTag, the repo
    // may be empty (first-ever deploy, or staging reset), so fall back to the
    // public App Runner hello-world image just to get the stack green. Any CI
    // deploy that forgets imageTag will visibly ship hello-world — that is the
    // signal, not a silent regression onto an old apps/api tag.
    const image = props.imageTag
      ? ContainerImage.fromEcrRepository(repository, props.imageTag)
      : ContainerImage.fromRegistry('public.ecr.aws/aws-containers/hello-app-runner:latest');

    taskDefinition.addContainer('api', {
      containerName: 'api',
      image,
      logging: LogDriver.awsLogs({
        logGroup,
        streamPrefix: 'api',
      }),
      environment: {
        OV_BLACK_ENV: props.envName,
        // apps/api binds Settings.env to the ENV var (pydantic env_prefix=''); its
        // Literal is local|staging|production, so 'prod' must become 'production' or
        // boot fails validation. Without this, Settings.env silently stayed 'local'
        // in staging (OV_BLACK_ENV above is not read by the app).
        ENV: props.envName === 'prod' ? 'production' : props.envName,
        // apps/api's boto3 agentcore client reads AWS_REGION (Settings.aws_region).
        // The AgentCore runtime lives wherever it was provisioned (default us-west-2),
        // independent of this ECS stack's region.
        AWS_REGION: props.agentcoreRegion,
        // Hand the ARNs to the app for reference/observability; the live values are
        // injected via the `secrets` block below (ECS native), NEVER baked into env.
        // The task role above is the only principal that can read them.
        SUPABASE_SERVICE_ROLE_SECRET_ARN: props.supabaseServiceRoleSecret.secretArn,
        SUPABASE_JWT_SECRET_ARN: props.supabaseJwtSecret.secretArn,
        DATABASE_URL_SECRET_ARN: props.databaseUrlSecret.secretArn,
        BEDROCK_AGENTCORE_RUNTIME_ARN_SECRET_ARN:
          props.bedrockAgentCoreRuntimeArnSecret.secretArn,
        AGENT_TOKEN_SIGNING_SECRET_ARN: props.agentTokenSigningSecret.secretArn,
        // WEB_ORIGIN drives invite redirect_to + CORS. Only injected once the web
        // app's staging origin is known; until then apps/api keeps its own default
        // rather than booting with WEB_ORIGIN='' (which would break both).
        ...(props.webOrigin ? { WEB_ORIGIN: props.webOrigin } : {}),
      },
      secrets: {
        // ECS natively injects each secret value as an env var the moment the task
        // starts. apps/api reads these directly (pydantic-settings) — there is no
        // boot-time Secrets Manager fetch, so the env names MUST match Settings.
        DATABASE_URL: EcsSecret.fromSecretsManager(props.databaseUrlSecret),
        SUPABASE_SERVICE_ROLE_KEY: EcsSecret.fromSecretsManager(props.supabaseServiceRoleSecret),
        // The supabase-jwt secret is JSON {url, issuer, jwks_url}; extract each field
        // into the flat env var apps/api's config + auth middleware actually read.
        SUPABASE_URL: EcsSecret.fromSecretsManager(props.supabaseJwtSecret, 'url'),
        SUPABASE_JWT_ISSUER: EcsSecret.fromSecretsManager(props.supabaseJwtSecret, 'issuer'),
        SUPABASE_JWKS_URL: EcsSecret.fromSecretsManager(props.supabaseJwtSecret, 'jwks_url'),
        BEDROCK_AGENTCORE_RUNTIME_ARN: EcsSecret.fromSecretsManager(
          props.bedrockAgentCoreRuntimeArnSecret,
        ),
        AGENT_TOKEN_SIGNING_SECRET: EcsSecret.fromSecretsManager(
          props.agentTokenSigningSecret,
        ),
      },
      portMappings: [{ containerPort: 8000, name: 'api' }],
      essential: true,
    });

    // ── Service security group ───────────────────────────────────────────────
    const serviceSg = new SecurityGroup(this, 'ApiServiceSg', {
      vpc,
      description: 'ov-black apps/api Fargate service - only accepts traffic from its ALB.',
      allowAllOutbound: true,
    });

    // Staging runs the service in public subnets with a public IP so tasks can
    // reach ECR / Secrets Manager / CloudWatch directly via the IGW (the VPC has
    // only an S3 gateway endpoint — no interface endpoints, no NAT for a private
    // subnet path). Prod keeps the private-subnet posture.
    const isStaging = props.envName === 'staging';
    const service = new FargateService(this, 'ApiService', {
      cluster,
      taskDefinition,
      desiredCount: 1,
      assignPublicIp: isStaging,
      vpcSubnets: {
        subnetType: isStaging ? SubnetType.PUBLIC : SubnetType.PRIVATE_WITH_EGRESS,
      },
      securityGroups: [serviceSg],
      circuitBreaker: { rollback: true },
      healthCheckGracePeriod: Duration.seconds(60),
      minHealthyPercent: 50,
      maxHealthyPercent: 200,
    });

    // ── ALB (public) ─────────────────────────────────────────────────────────
    const albSg = new SecurityGroup(this, 'ApiAlbSg', {
      vpc,
      description: 'ov-black apps/api ALB - public HTTP ingress for M001 staging (no TLS yet).',
      allowAllOutbound: true,
    });
    albSg.addIngressRule(Peer.anyIpv4(), Port.tcp(80), 'HTTP from Internet (M001 staging).');

    const alb = new ApplicationLoadBalancer(this, 'ApiAlb', {
      vpc,
      internetFacing: true,
      securityGroup: albSg,
      vpcSubnets: { subnetType: SubnetType.PUBLIC },
      loadBalancerName: `ov-black-api-${props.envName}`,
      // SSE turn streams run 10–30s end-to-end; ALB's default 60s idle timeout
      // can cut a long generation in half. 120s gives the upper bound (~90s
      // worst case) + ~30% headroom without masking a legitimately stuck
      // upstream. The listener inherits this from the ALB — do NOT set it on
      // `addListener` (that property does not exist there).
      idleTimeout: Duration.seconds(120),
    });

    const targetGroup = new ApplicationTargetGroup(this, 'ApiTargetGroup', {
      vpc,
      port: 8000,
      protocol: ApplicationProtocol.HTTP,
      targetType: TargetType.IP,
      healthCheck: {
        // apps/api exposes /health; hello-world fallback only answers on /.
        path: props.imageTag ? '/health' : '/',
        healthyHttpCodes: '200',
        interval: Duration.seconds(30),
        timeout: Duration.seconds(5),
        healthyThresholdCount: 2,
        unhealthyThresholdCount: 3,
      },
      deregistrationDelay: Duration.seconds(15),
      targetGroupName: `ov-black-api-${props.envName}`,
    });

    // ALB must be allowed to reach the service on the container port.
    serviceSg.addIngressRule(
      albSg,
      Port.tcp(8000),
      'ALB to Fargate task on container port 8000.',
    );
    targetGroup.addTarget(service);

    alb.addListener('HttpListener', {
      port: 80,
      protocol: ApplicationProtocol.HTTP,
      defaultAction: ListenerAction.forward([targetGroup]),
    });

    this.albDnsName = alb.loadBalancerDnsName;
    this.ecrRepositoryUri = repository.repositoryUri;
    this.logGroupName = logGroup.logGroupName;

    new CfnOutput(this, 'AlbDnsName', {
      value: alb.loadBalancerDnsName,
      description: 'Public ALB DNS name — hit /health on this to verify the deploy.',
      exportName: `ov-black-${props.envName}-api-alb-dns`,
    });
    new CfnOutput(this, 'EcrRepositoryUri', {
      value: repository.repositoryUri,
      description: 'ECR repository URI — push images here for the ECS service to pull.',
      exportName: `ov-black-${props.envName}-api-ecr-uri`,
    });
    new CfnOutput(this, 'LogGroupName', {
      value: logGroup.logGroupName,
      description: 'CloudWatch log group receiving apps/api container logs.',
      exportName: `ov-black-${props.envName}-api-log-group`,
    });
  }
}
