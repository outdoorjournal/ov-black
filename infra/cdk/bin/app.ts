#!/usr/bin/env node
import 'source-map-support/register';
import { App } from 'aws-cdk-lib';
import { loadEnvConfig } from '../config/env';
import { SecretsStack } from '../lib/secrets-stack';
import { ApiStack } from '../lib/api-stack';

const app = new App();
const config = loadEnvConfig(app);
const awsEnv = { account: config.account, region: config.region };
const imageTagContext = app.node.tryGetContext('imageTag') as string | undefined;
const webImageTagContext = app.node.tryGetContext('webImageTag') as string | undefined;

const secretsStack = new SecretsStack(app, `OvBlackSecrets-${config.envName}`, {
  envName: config.envName,
  env: awsEnv,
  description: `ov-black Secrets Manager entries for ${config.envName} (Supabase service role + JWT).`,
});

const apiStack = new ApiStack(app, `OvBlackApi-${config.envName}`, {
  envName: config.envName,
  vpcId: config.vpcId,
  availabilityZones: config.availabilityZones,
  publicSubnetIds: config.publicSubnetIds,
  privateSubnetIds: config.privateSubnetIds,
  supabaseServiceRoleSecret: secretsStack.supabaseServiceRole,
  supabaseJwtSecret: secretsStack.supabaseJwt,
  databaseUrlSecret: secretsStack.databaseUrl,
  bedrockAgentCoreRuntimeArnSecret: secretsStack.bedrockAgentCoreRuntimeArn,
  agentTokenSigningSecret: secretsStack.agentTokenSigningSecret,
  inventoryProviderKeysSecret: secretsStack.inventoryProviderKeys,
  webOrigin: config.webOrigin,
  agentcoreRegion: config.agentcoreRegion,
  hostedZoneId: config.hostedZoneId,
  zoneName: config.zoneName,
  webHost: config.webHost,
  apiHost: config.apiHost,
  supabaseUrl: config.supabaseUrl,
  supabaseAnonKey: config.supabaseAnonKey,
  mapboxToken: config.mapboxToken,
  ...(imageTagContext ? { imageTag: imageTagContext } : {}),
  ...(webImageTagContext ? { webImageTag: webImageTagContext } : {}),
  env: awsEnv,
  description: `ov-black apps/api on ECS Fargate behind an ALB for ${config.envName} (D002).`,
});
apiStack.addDependency(secretsStack);

app.synth();
