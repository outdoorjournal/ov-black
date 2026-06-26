import { Stack, type StackProps, CfnOutput, Duration, RemovalPolicy } from 'aws-cdk-lib';
import { Peer, Port, SecurityGroup, SubnetType, Vpc } from 'aws-cdk-lib/aws-ec2';
import { Repository, TagStatus } from 'aws-cdk-lib/aws-ecr';
import {
  Cluster,
  ContainerImage,
  CpuArchitecture,
  FargateService,
  FargateTaskDefinition,
  LogDriver,
  OperatingSystemFamily,
  Secret as EcsSecret,
} from 'aws-cdk-lib/aws-ecs';
import {
  ApplicationListenerRule,
  ApplicationLoadBalancer,
  ApplicationProtocol,
  ApplicationTargetGroup,
  ListenerAction,
  ListenerCondition,
  TargetType,
} from 'aws-cdk-lib/aws-elasticloadbalancingv2';
import { Certificate, CertificateValidation } from 'aws-cdk-lib/aws-certificatemanager';
import { ARecord, HostedZone, RecordTarget } from 'aws-cdk-lib/aws-route53';
import { LoadBalancerTarget } from 'aws-cdk-lib/aws-route53-targets';
import { Effect, PolicyStatement, Role, ServicePrincipal } from 'aws-cdk-lib/aws-iam';
import { LogGroup, RetentionDays } from 'aws-cdk-lib/aws-logs';
import { BlockPublicAccess, Bucket, BucketEncryption, HttpMethods } from 'aws-cdk-lib/aws-s3';
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
  /** One JSON secret holding every vendor key; ApiStack extracts each field (google_places, duffel). */
  readonly inventoryProviderKeysSecret: SmSecret;
  /** Web app origin → WEB_ORIGIN. Empty means "not wired yet"; we skip injection then. */
  readonly webOrigin: string;
  /** Region of the Bedrock AgentCore runtime → AWS_REGION for apps/api's boto3 client. */
  readonly agentcoreRegion: string;
  /** Image tag to deploy. Defaults to `latest`; CI overrides via `-c imageTag=...`. */
  readonly imageTag?: string;
  /** apps/web image tag → pulled from the web ECR repo. `-c webImageTag=...`. */
  readonly webImageTag?: string;
  /** Route53 hosted zone hosting the web + api A records (e.g. dev.outdoorvoyage.com). */
  readonly hostedZoneId: string;
  readonly zoneName: string;
  /** Web app FQDN: ALB HTTPS default action + apex A record (e.g. black.dev.outdoorvoyage.com). */
  readonly webHost: string;
  /** API FQDN: ALB host-header rule + A record (e.g. api.black.dev.outdoorvoyage.com). */
  readonly apiHost: string;
  /** Public (browser-exposed) web config → injected into apps/web as OVB_* runtime env. */
  readonly supabaseUrl: string;
  readonly supabaseAnonKey: string;
  readonly mapboxToken: string;
}

/**
 * apps/api AND apps/web on ECS Fargate behind ONE shared, internet-facing ALB
 * (D002). Consumes the existing NetworkStack's VPC (Control Tower: provisioned in
 * a separate account-bound repo) by ID + subnet attributes so this stack stays
 * hermetic and synth works without AWS credentials.
 *
 * Surfaces:
 *   - One ALB: HTTPS:443 (ACM cert, DNS-validated) → web TG (:3000) by default,
 *     host api.<domain> → api TG (:8000); HTTP:80 redirects to 443.
 *   - Route53 alias records for the web (apex) + api hosts at the ALB.
 *   - Two ECR repos (ov-black-api, ov-black-web) + two CloudWatch log groups.
 *   - IAM task role scoped to GetSecretValue on exactly the API's secrets; the
 *     web task carries no secrets (NEXT_PUBLIC_* are baked at build time).
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

    // ECR repo for the apps/web container (same lifecycle posture as the API repo).
    const webRepository = new Repository(this, 'WebRepository', {
      repositoryName: `ov-black-web-${props.envName}`,
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

    // ── CloudWatch log groups ────────────────────────────────────────────────
    const logGroup = new LogGroup(this, 'ApiLogGroup', {
      logGroupName: `/ecs/ov-black-api-${props.envName}`,
      retention: RetentionDays.ONE_MONTH,
      removalPolicy: props.envName === 'prod' ? RemovalPolicy.RETAIN : RemovalPolicy.DESTROY,
    });

    const webLogGroup = new LogGroup(this, 'WebLogGroup', {
      logGroupName: `/ecs/ov-black-web-${props.envName}`,
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
      // Run on Graviton (arm64): cheaper compute AND it lets the images build
      // natively on Apple-Silicon dev machines (no slow amd64 QEMU emulation).
      // apps/agent already targets arm64; the apps/api + apps/web Dockerfiles are
      // arch-neutral, so we just build --platform linux/arm64.
      runtimePlatform: {
        cpuArchitecture: CpuArchitecture.ARM64,
        operatingSystemFamily: OperatingSystemFamily.LINUX,
      },
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
          props.inventoryProviderKeysSecret.secretArn,
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
    // ── Document vault bucket (M003/V3) ──────────────────────────────────────
    // SSE-KMS at rest via the AWS-managed aws/s3 key (D-VAULT: AWS-managed for
    // the MVP; a customer-managed key is a future tightening). Public access is
    // fully blocked + TLS enforced; the browser reaches objects only via
    // short-TTL presigned URLs minted by the API. A CORS rule lets the browser
    // PUT/GET directly from the web origin. Versioned so an overwrite/delete is
    // recoverable for HNW documents.
    const vaultBucket = new Bucket(this, 'DocumentVault', {
      bucketName: `ov-black-vault-${props.envName}`,
      encryption: BucketEncryption.KMS_MANAGED,
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      versioned: true,
      removalPolicy: props.envName === 'prod' ? RemovalPolicy.RETAIN : RemovalPolicy.DESTROY,
      cors: [
        {
          allowedMethods: [HttpMethods.PUT, HttpMethods.GET, HttpMethods.HEAD],
          // The presigned PUT/GET is issued to the signed-in web origin only.
          allowedOrigins: props.webOrigin ? [props.webOrigin] : ['*'],
          allowedHeaders: ['*'],
          exposedHeaders: ['ETag'],
          maxAge: 3000,
        },
      ],
    });
    // The task role generates presigned URLs + may read/write objects directly.
    // grantReadWrite covers the S3 actions; the aws/s3 managed key is granted to
    // account principals via the S3 service, so no explicit KMS grant is needed.
    vaultBucket.grantReadWrite(taskDefinition.taskRole);

    // Execution role (ECR pull + CloudWatch write) is added automatically by
    // the FargateTaskDefinition L2 when we attach the image and log driver.

    // Image selection: when CI (or a manual deploy) passes `-c imageTag=<sha>`
    // we pull that tag from the stack's ECR repo. With no imageTag, the repo
    // may be empty (first-ever deploy, or staging reset), so fall back to a
    // public multi-arch busybox placeholder just to get the stack green. Two
    // hard requirements drove this choice: (1) MUST be multi-arch — the task
    // runs on arm64 (Graviton), and the old hello-app-runner image was
    // amd64-only, so an arm64 task can't run it; (2) MUST be able to listen on
    // the *container* port (8000), which the ALB health check targets — busybox
    // httpd takes `-p`, whereas a stock nginx is pinned to :80. The command
    // below serves a 200 on `/`. Any deploy that forgets imageTag will visibly
    // ship busybox — that is the signal, not a silent regression onto an old tag.
    const usingFallbackImage = !props.imageTag;
    const image = props.imageTag
      ? ContainerImage.fromEcrRepository(repository, props.imageTag)
      : ContainerImage.fromRegistry('public.ecr.aws/docker/library/busybox:latest');

    taskDefinition.addContainer('api', {
      containerName: 'api',
      image,
      // Fallback only: make busybox httpd serve a 200 on `/` at the container
      // port (8000) so the ALB health check passes. The real apps/api image has
      // its own entrypoint and ignores this.
      ...(usingFallbackImage
        ? { command: ['sh', '-c', 'echo ok > /tmp/index.html && exec httpd -f -p 8000 -h /tmp'] }
        : {}),
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
        // Real providers only. The default 'ov,mock' would CRASH boot here: the mock
        // provider eagerly loads tests/fixtures/mock_inventory.json in __init__, and
        // the image excludes tests/ (.dockerignore). google_places + duffel are enabled
        // now that their keys are wired below (GOOGLE_PLACES_API_KEY / DUFFEL_API_KEY);
        // ratehawk joins once its key lands — see the runbook. Until the operator populates
        // the real key, each provider degrades to [] (a placeholder key 4xx/401s, never a
        // boot crash).
        INVENTORY_PROVIDERS_ENABLED: 'ov,google_places,duffel',
        // Document vault bucket (M003/V3). Not a secret — the bucket name is
        // safe in plain env; access is gated by the task role + presigned URLs.
        VAULT_BUCKET_NAME: vaultBucket.bucketName,
        // Hand the ARNs to the app for reference/observability; the live values are
        // injected via the `secrets` block below (ECS native), NEVER baked into env.
        // The task role above is the only principal that can read them.
        SUPABASE_SERVICE_ROLE_SECRET_ARN: props.supabaseServiceRoleSecret.secretArn,
        SUPABASE_JWT_SECRET_ARN: props.supabaseJwtSecret.secretArn,
        DATABASE_URL_SECRET_ARN: props.databaseUrlSecret.secretArn,
        BEDROCK_AGENTCORE_RUNTIME_ARN_SECRET_ARN:
          props.bedrockAgentCoreRuntimeArnSecret.secretArn,
        AGENT_TOKEN_SIGNING_SECRET_ARN: props.agentTokenSigningSecret.secretArn,
        // One secret, two JSON fields → two env vars (extracted in the secrets block below).
        INVENTORY_PROVIDER_KEYS_SECRET_ARN: props.inventoryProviderKeysSecret.secretArn,
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
        // Both vendor keys live in one JSON secret (cost) — extract each field into
        // the flat env var apps/api reads, exactly like the supabase-jwt fields above.
        GOOGLE_PLACES_API_KEY: EcsSecret.fromSecretsManager(
          props.inventoryProviderKeysSecret,
          'google_places',
        ),
        DUFFEL_API_KEY: EcsSecret.fromSecretsManager(props.inventoryProviderKeysSecret, 'duffel'),
      },
      portMappings: [{ containerPort: 8000, name: 'api' }],
      essential: true,
    });

    // ── apps/web task definition + container ─────────────────────────────────
    // The web image is self-contained: NEXT_PUBLIC_* values are baked into the
    // bundle at `next build` time (see apps/web/Dockerfile), so the runtime needs
    // NO secrets and the web task role gets NO Secrets Manager / Bedrock grants.
    // Multi-arch busybox placeholder (arm64-capable, listens on the container
    // port 3000) when no webImageTag — same rationale as the API fallback above.
    const usingWebFallbackImage = !props.webImageTag;
    const webImage = props.webImageTag
      ? ContainerImage.fromEcrRepository(webRepository, props.webImageTag)
      : ContainerImage.fromRegistry('public.ecr.aws/docker/library/busybox:latest');

    const webTaskDefinition = new FargateTaskDefinition(this, 'WebTaskDefinition', {
      cpu: 512,
      memoryLimitMiB: 1024,
      family: `ov-black-web-${props.envName}`,
      // arm64 (Graviton) — same rationale as the API task def above.
      runtimePlatform: {
        cpuArchitecture: CpuArchitecture.ARM64,
        operatingSystemFamily: OperatingSystemFamily.LINUX,
      },
    });

    webTaskDefinition.addContainer('web', {
      containerName: 'web',
      image: webImage,
      // Fallback only: busybox httpd serves a 200 on `/` at the web container
      // port (3000) for the ALB health check. The real apps/web image ignores it.
      ...(usingWebFallbackImage
        ? { command: ['sh', '-c', 'echo ok > /tmp/index.html && exec httpd -f -p 3000 -h /tmp'] }
        : {}),
      logging: LogDriver.awsLogs({
        logGroup: webLogGroup,
        streamPrefix: 'web',
      }),
      environment: {
        NODE_ENV: 'production',
        // Next's standalone server reads PORT + HOSTNAME at startup.
        PORT: '3000',
        HOSTNAME: '0.0.0.0',
        // Public web config read at RUNTIME (see apps/web/lib/env.ts). OVB_* names
        // are deliberately NOT NEXT_PUBLIC_ so Next never inlines them at build —
        // one image, configured per-environment here. All are browser-public.
        OVB_API_BASE_URL: `https://${props.apiHost}`,
        OVB_SUPABASE_URL: props.supabaseUrl,
        OVB_SUPABASE_ANON_KEY: props.supabaseAnonKey,
        OVB_MAPBOX_TOKEN: props.mapboxToken,
      },
      portMappings: [{ containerPort: 3000, name: 'web' }],
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

    // apps/web service — same subnet/public-IP posture as the API service.
    const webServiceSg = new SecurityGroup(this, 'WebServiceSg', {
      vpc,
      description: 'ov-black apps/web Fargate service - only accepts traffic from its ALB.',
      allowAllOutbound: true,
    });
    const webService = new FargateService(this, 'WebService', {
      cluster,
      taskDefinition: webTaskDefinition,
      desiredCount: 1,
      assignPublicIp: isStaging,
      vpcSubnets: {
        subnetType: isStaging ? SubnetType.PUBLIC : SubnetType.PRIVATE_WITH_EGRESS,
      },
      securityGroups: [webServiceSg],
      circuitBreaker: { rollback: true },
      healthCheckGracePeriod: Duration.seconds(60),
      minHealthyPercent: 50,
      maxHealthyPercent: 200,
    });

    // ── ALB (public) ─────────────────────────────────────────────────────────
    const albSg = new SecurityGroup(this, 'ApiAlbSg', {
      vpc,
      description: 'ov-black shared ALB - public HTTP(80, redirect) + HTTPS(443) ingress.',
      allowAllOutbound: true,
    });
    albSg.addIngressRule(Peer.anyIpv4(), Port.tcp(80), 'HTTP from Internet (redirects to 443).');
    albSg.addIngressRule(Peer.anyIpv4(), Port.tcp(443), 'HTTPS from Internet.');

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

    // ── apps/web target group ────────────────────────────────────────────────
    const webTargetGroup = new ApplicationTargetGroup(this, 'WebTargetGroup', {
      vpc,
      port: 3000,
      protocol: ApplicationProtocol.HTTP,
      targetType: TargetType.IP,
      healthCheck: {
        // apps/web exposes /health (app/health/route.ts); the hello-world
        // fallback image only answers on /.
        path: props.webImageTag ? '/health' : '/',
        healthyHttpCodes: '200',
        interval: Duration.seconds(30),
        timeout: Duration.seconds(5),
        healthyThresholdCount: 2,
        unhealthyThresholdCount: 3,
      },
      deregistrationDelay: Duration.seconds(15),
      targetGroupName: `ov-black-web-${props.envName}`,
    });
    webServiceSg.addIngressRule(
      albSg,
      Port.tcp(3000),
      'ALB to web Fargate task on container port 3000.',
    );
    webTargetGroup.addTarget(webService);

    // ── TLS certificate (regional, DNS-validated against the shared zone) ──────
    // fromHostedZoneAttributes (NOT fromLookup) + CertificateValidation.fromDns
    // keep `cdk synth` hermetic — no AWS calls at synth. At deploy, CloudFormation
    // writes the validation CNAMEs into the same-account zone automatically.
    const zone = HostedZone.fromHostedZoneAttributes(this, 'PlatformZone', {
      hostedZoneId: props.hostedZoneId,
      zoneName: props.zoneName,
    });
    const certificate = new Certificate(this, 'AlbCertificate', {
      domainName: props.webHost,
      // Wildcard covers apiHost (api.<webHost>) and any future <x>.<webHost>.
      subjectAlternativeNames: [`*.${props.webHost}`],
      validation: CertificateValidation.fromDns(zone),
    });

    // ── Listeners: HTTPS:443 (web default + api host rule) + HTTP:80 redirect ──
    const httpsListener = alb.addListener('HttpsListener', {
      port: 443,
      protocol: ApplicationProtocol.HTTPS,
      certificates: [certificate],
      defaultAction: ListenerAction.forward([webTargetGroup]),
    });
    new ApplicationListenerRule(this, 'ApiHostRule', {
      listener: httpsListener,
      priority: 10,
      conditions: [ListenerCondition.hostHeaders([props.apiHost])],
      action: ListenerAction.forward([targetGroup]),
    });
    // Construct id is deliberately 'HttpListener' (NOT 'HttpRedirect'): the
    // pre-TLS stack already had an HTTP:80 listener under that id. Reusing it
    // keeps the same CloudFormation logical id, so this deploy MODIFIES the
    // existing port-80 listener in place (forward → redirect) instead of trying
    // to create a second listener on port 80 — which collides ("A listener
    // already exists on this port") because CFN creates before it deletes.
    alb.addListener('HttpListener', {
      port: 80,
      protocol: ApplicationProtocol.HTTP,
      defaultAction: ListenerAction.redirect({
        protocol: 'HTTPS',
        port: '443',
        permanent: true,
      }),
    });

    // ── DNS: alias both hosts at the shared ALB ───────────────────────────────
    // recordName is relative to the zone, so strip the zone suffix from each FQDN.
    const zoneSuffix = `.${props.zoneName}`;
    const webRecordName = props.webHost.endsWith(zoneSuffix)
      ? props.webHost.slice(0, -zoneSuffix.length)
      : props.webHost;
    const apiRecordName = props.apiHost.endsWith(zoneSuffix)
      ? props.apiHost.slice(0, -zoneSuffix.length)
      : props.apiHost;
    new ARecord(this, 'WebAliasRecord', {
      zone,
      recordName: webRecordName,
      target: RecordTarget.fromAlias(new LoadBalancerTarget(alb)),
    });
    new ARecord(this, 'ApiAliasRecord', {
      zone,
      recordName: apiRecordName,
      target: RecordTarget.fromAlias(new LoadBalancerTarget(alb)),
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
    new CfnOutput(this, 'WebEcrRepositoryUri', {
      value: webRepository.repositoryUri,
      description: 'ECR repository URI — push apps/web images here.',
      exportName: `ov-black-${props.envName}-web-ecr-uri`,
    });
    new CfnOutput(this, 'WebUrl', {
      value: `https://${props.webHost}`,
      description: 'Public web URL (apex) served by the shared ALB.',
      exportName: `ov-black-${props.envName}-web-url`,
    });
    new CfnOutput(this, 'ApiUrl', {
      value: `https://${props.apiHost}`,
      description: 'Public API URL served by the shared ALB.',
      exportName: `ov-black-${props.envName}-api-url`,
    });
  }
}
