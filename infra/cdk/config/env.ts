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
   * Origin of the advisor/client web app (e.g. https://staging.ov.black). Injected
   * as WEB_ORIGIN so the API builds correct magic-link redirect_to targets and CORS
   * allow-lists. Empty until the web app's staging origin exists — the API then keeps
   * its own localhost default and is NOT injected (see api-stack.ts).
   */
  readonly webOrigin: string;
  /**
   * Region where the Bedrock AgentCore runtime is provisioned. Injected as AWS_REGION
   * so apps/api's boto3 agentcore client targets the runtime. Defaults to us-west-2
   * (AgentCore early-availability + apps/api's own default) — it does NOT have to match
   * the ECS deploy region, and the runtime ARN encodes its own region regardless.
   */
  readonly agentcoreRegion: string;
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
}

const DUMMY = {
  account: '000000000000',
  region: 'us-east-1',
  vpcId: 'vpc-00000000',
  azs: ['us-east-1a', 'us-east-1b'],
  publicSubnets: ['subnet-public-a', 'subnet-public-b'],
  privateSubnets: ['subnet-private-a', 'subnet-private-b'],
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

  // WEB_ORIGIN has no safe dummy — an empty value means "operator hasn't wired the
  // web app's staging origin yet", and api-stack.ts skips injecting it so the API
  // keeps its own default rather than booting with WEB_ORIGIN=''.
  const webOrigin = raw.webOrigin ?? '';
  const agentcoreRegion = raw.agentcoreRegion || 'us-west-2';

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
  };
}
