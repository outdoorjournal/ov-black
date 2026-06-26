import type { Construct } from 'constructs';

/**
 * Per-environment configuration loaded from CDK context (`cdk.json` → `ov-black:envs`)
 * with `CDK_DEFAULT_ACCOUNT` / `CDK_DEFAULT_REGION` as escape hatches for the
 * SSO'd caller (Control Tower: staging and prod live in their own accounts).
 *
 * The VPC is provisioned by a separate NetworkStack (owned outside this repo);
 * we consume it by ID + subnet attributes so synth stays hermetic.
 */
export interface EnvConfig {
  readonly envName: 'staging' | 'prod';
  readonly account: string;
  readonly region: string;
  readonly vpcId: string;
  readonly availabilityZones: string[];
  readonly publicSubnetIds: string[];
  readonly privateSubnetIds: string[];
  /**
   * Origin of the advisor/client web app (https://<webHost>). Injected as
   * WEB_ORIGIN so the API builds correct magic-link redirect_to targets and CORS
   * allow-lists. Derived from webHost in loadEnvConfig unless explicitly overridden.
   */
  readonly webOrigin: string;
  /**
   * Region where the Bedrock AgentCore runtime is provisioned. Injected as AWS_REGION
   * so apps/api's boto3 agentcore client targets the runtime. Defaults to us-west-2
   * (AgentCore early-availability + apps/api's own default) — it does NOT have to match
   * the ECS deploy region, and the runtime ARN encodes its own region regardless.
   */
  readonly agentcoreRegion: string;
  /** Route53 hosted zone for the web + api DNS records (e.g. dev.outdoorvoyage.com). */
  readonly hostedZoneId: string;
  readonly zoneName: string;
  /** Public FQDNs served by the shared ALB. webHost is the apex; apiHost the API host. */
  readonly webHost: string;
  readonly apiHost: string;
  /**
   * Public (browser-exposed) web config, injected into apps/web as OVB_* runtime
   * env. Non-secret by design — the anon key + Mapbox token ship to the browser —
   * so they live in plain context, not Secrets Manager.
   */
  readonly supabaseUrl: string;
  readonly supabaseAnonKey: string;
  readonly mapboxToken: string;
}

interface RawEnvConfig {
  account?: string;
  region?: string;
  vpcId?: string;
  availabilityZones?: string[];
  publicSubnetIds?: string[];
  privateSubnetIds?: string[];
  webOrigin?: string;
  agentcoreRegion?: string;
  hostedZoneId?: string;
  zoneName?: string;
  webHost?: string;
  apiHost?: string;
  supabaseUrl?: string;
  supabaseAnonKey?: string;
  mapboxToken?: string;
}

const DUMMY = {
  account: '000000000000',
  region: 'us-east-1',
  vpcId: 'vpc-00000000',
  azs: ['us-east-1a', 'us-east-1b'],
  publicSubnets: ['subnet-public-a', 'subnet-public-b'],
  privateSubnets: ['subnet-private-a', 'subnet-private-b'],
  // Internally consistent placeholders (webHost/apiHost end with zoneName) so
  // hermetic synth produces a valid cert + record-name derivation without creds.
  hostedZoneId: 'Z00000000000000000000',
  zoneName: 'dev.outdoorvoyage.com',
  webHost: 'black.dev.outdoorvoyage.com',
  apiHost: 'api.black.dev.outdoorvoyage.com',
  supabaseUrl: 'https://example.supabase.co',
  supabaseAnonKey: 'dummy-anon-key',
  mapboxToken: 'pk.dummy',
} as const;

export function loadEnvConfig(scope: Construct): EnvConfig {
  const envName = (scope.node.tryGetContext('env') as string | undefined) ?? 'staging';
  if (envName !== 'staging' && envName !== 'prod') {
    throw new Error(
      `Unknown CDK context 'env'='${envName}'. Pass -c env=staging or -c env=prod.`,
    );
  }

  const envs = (scope.node.tryGetContext('ov-black:envs') ?? {}) as Record<string, RawEnvConfig>;
  const raw = envs[envName] ?? {};

  const account = raw.account || process.env.CDK_DEFAULT_ACCOUNT || DUMMY.account;
  const region = raw.region || process.env.CDK_DEFAULT_REGION || DUMMY.region;

  // Fall back to dummy values so `cdk synth` stays hermetic without AWS creds.
  // Real staging/prod deploys must populate these via cdk.json or `-c` overrides.
  const vpcId = raw.vpcId || DUMMY.vpcId;
  const availabilityZones =
    raw.availabilityZones && raw.availabilityZones.length > 0
      ? raw.availabilityZones
      : [...DUMMY.azs];
  const publicSubnetIds =
    raw.publicSubnetIds && raw.publicSubnetIds.length > 0
      ? raw.publicSubnetIds
      : [...DUMMY.publicSubnets];
  const privateSubnetIds =
    raw.privateSubnetIds && raw.privateSubnetIds.length > 0
      ? raw.privateSubnetIds
      : [...DUMMY.privateSubnets];

  const agentcoreRegion = raw.agentcoreRegion || 'us-west-2';

  // DNS + public hostnames for the shared ALB. Dummy fallbacks keep `cdk synth`
  // hermetic; real values come from cdk.json (or `-c` overrides).
  const hostedZoneId = raw.hostedZoneId || DUMMY.hostedZoneId;
  const zoneName = raw.zoneName || DUMMY.zoneName;
  const webHost = raw.webHost || DUMMY.webHost;
  const apiHost = raw.apiHost || DUMMY.apiHost;
  const supabaseUrl = raw.supabaseUrl || DUMMY.supabaseUrl;
  const supabaseAnonKey = raw.supabaseAnonKey || DUMMY.supabaseAnonKey;
  const mapboxToken = raw.mapboxToken || DUMMY.mapboxToken;

  // WEB_ORIGIN (magic-link redirect_to + CORS allow-list) is the web app's origin.
  // Derive it from webHost so there is a single source of truth; an explicit
  // webOrigin in context still wins.
  const webOrigin = raw.webOrigin || `https://${webHost}`;

  return {
    envName,
    account,
    region,
    vpcId,
    availabilityZones,
    publicSubnetIds,
    privateSubnetIds,
    webOrigin,
    agentcoreRegion,
    hostedZoneId,
    zoneName,
    webHost,
    apiHost,
    supabaseUrl,
    supabaseAnonKey,
    mapboxToken,
  };
}
