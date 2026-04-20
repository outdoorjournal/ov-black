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
}

interface RawEnvConfig {
  account?: string;
  region?: string;
  vpcId?: string;
  availabilityZones?: string[];
  publicSubnetIds?: string[];
  privateSubnetIds?: string[];
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

  return {
    envName,
    account,
    region,
    vpcId,
    availabilityZones,
    publicSubnetIds,
    privateSubnetIds,
  };
}
