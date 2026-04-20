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
  readonly bedrockAgentCoreRuntimeArnSecret: SmSecret;
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
          props.bedrockAgentCoreRuntimeArnSecret.secretArn,
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

    taskDefinition.addContainer('api', {
      containerName: 'api',
      image: ContainerImage.fromEcrRepository(repository, props.imageTag ?? 'latest'),
      logging: LogDriver.awsLogs({
        logGroup,
        streamPrefix: 'api',
      }),
      environment: {
        OV_BLACK_ENV: props.envName,
        // Hand the ARNs to the app so it can fetch the live values at boot;
        // the values themselves are NEVER baked into env. The task role above
        // is the only thing that can read them.
        SUPABASE_SERVICE_ROLE_SECRET_ARN: props.supabaseServiceRoleSecret.secretArn,
        SUPABASE_JWT_SECRET_ARN: props.supabaseJwtSecret.secretArn,
        BEDROCK_AGENTCORE_RUNTIME_ARN_SECRET_ARN:
          props.bedrockAgentCoreRuntimeArnSecret.secretArn,
      },
      secrets: {
        // ECS also natively injects the secret values as envvars. Apps that
        // prefer SDK-side fetch can ignore these and use the ARNs above.
        SUPABASE_SERVICE_ROLE_KEY: EcsSecret.fromSecretsManager(props.supabaseServiceRoleSecret),
        SUPABASE_JWT: EcsSecret.fromSecretsManager(props.supabaseJwtSecret),
        BEDROCK_AGENTCORE_RUNTIME_ARN: EcsSecret.fromSecretsManager(
          props.bedrockAgentCoreRuntimeArnSecret,
        ),
      },
      portMappings: [{ containerPort: 8000, name: 'api' }],
      essential: true,
    });

    // ── Service security group ───────────────────────────────────────────────
    const serviceSg = new SecurityGroup(this, 'ApiServiceSg', {
      vpc,
      description: 'ov-black apps/api Fargate service — only accepts traffic from its ALB.',
      allowAllOutbound: true,
    });

    const service = new FargateService(this, 'ApiService', {
      cluster,
      taskDefinition,
      desiredCount: 1,
      assignPublicIp: false,
      vpcSubnets: { subnetType: SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [serviceSg],
      circuitBreaker: { rollback: true },
      healthCheckGracePeriod: Duration.seconds(60),
      minHealthyPercent: 50,
      maxHealthyPercent: 200,
    });

    // ── ALB (public) ─────────────────────────────────────────────────────────
    const albSg = new SecurityGroup(this, 'ApiAlbSg', {
      vpc,
      description: 'ov-black apps/api ALB — public HTTP ingress for M001 staging (no TLS yet).',
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
        path: '/health',
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
      'ALB → Fargate task on container port 8000.',
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
