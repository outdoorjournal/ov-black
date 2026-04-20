import { Stack, type StackProps, CfnOutput, RemovalPolicy, SecretValue } from 'aws-cdk-lib';
import { Secret } from 'aws-cdk-lib/aws-secretsmanager';
import type { Construct } from 'constructs';

export interface SecretsStackProps extends StackProps {
  readonly envName: 'staging' | 'prod';
}

/**
 * Secrets Manager entries consumed by apps/api. Seeded with empty-string
 * placeholder values so `cdk deploy` from a clean checkout succeeds; the
 * real values are populated out-of-band by the account operator before the
 * API container can use them (invite redemption + Supabase JWT verification
 * both fail fast on empty placeholders — by design).
 *
 * Never log these values. See R017 / D013.
 */
export class SecretsStack extends Stack {
  readonly supabaseServiceRole: Secret;
  readonly supabaseJwt: Secret;
  readonly bedrockAgentCoreRuntimeArn: Secret;

  constructor(scope: Construct, id: string, props: SecretsStackProps) {
    super(scope, id, props);

    const namePrefix = `ov-black/${props.envName}`;

    this.supabaseServiceRole = new Secret(this, 'SupabaseServiceRole', {
      secretName: `${namePrefix}/supabase-service-role`,
      description:
        'Supabase service role key used by apps/api to sign/verify server-to-server calls (invite redemption, magic-link emit).',
      secretStringValue: SecretValue.unsafePlainText(''),
      removalPolicy: props.envName === 'prod' ? RemovalPolicy.RETAIN : RemovalPolicy.DESTROY,
    });

    this.supabaseJwt = new Secret(this, 'SupabaseJwt', {
      secretName: `${namePrefix}/supabase-jwt`,
      description:
        'Supabase JWT issuer + JWKS URL consumed by apps/api auth middleware to verify user tokens on every non-/health route.',
      secretStringValue: SecretValue.unsafePlainText(
        JSON.stringify({ issuer: '', jwks_url: '' }),
      ),
      removalPolicy: props.envName === 'prod' ? RemovalPolicy.RETAIN : RemovalPolicy.DESTROY,
    });

    // The Bedrock AgentCore runtime itself (the agent) is provisioned OUT OF BAND
    // in the AWS console for M001 — CDK-managed agent provisioning is deferred
    // until S05 stabilizes. The operator populates this Secret with the runtime
    // ARN (`arn:aws:bedrock-agentcore:<region>:<account>:runtime/<runtime-id>`)
    // before the API container is first exercised against staging; apps/api reads
    // it at boot and refuses to start the Bedrock client if the value is empty.
    this.bedrockAgentCoreRuntimeArn = new Secret(this, 'BedrockAgentCoreRuntimeArn', {
      secretName: `${namePrefix}/bedrock-agentcore-runtime-arn`,
      description:
        'Bedrock AgentCore runtime ARN consumed by apps/api to InvokeAgentRuntime. Populated out-of-band by the operator after console-side agent creation.',
      secretStringValue: SecretValue.unsafePlainText(''),
      removalPolicy: props.envName === 'prod' ? RemovalPolicy.RETAIN : RemovalPolicy.DESTROY,
    });

    new CfnOutput(this, 'SupabaseServiceRoleArn', {
      value: this.supabaseServiceRole.secretArn,
      description: 'ARN of the Supabase service-role-key secret.',
      exportName: `ov-black-${props.envName}-supabase-service-role-arn`,
    });

    new CfnOutput(this, 'SupabaseJwtArn', {
      value: this.supabaseJwt.secretArn,
      description: 'ARN of the Supabase JWT issuer + JWKS URL secret.',
      exportName: `ov-black-${props.envName}-supabase-jwt-arn`,
    });

    new CfnOutput(this, 'BedrockAgentCoreRuntimeArnArn', {
      value: this.bedrockAgentCoreRuntimeArn.secretArn,
      description: 'ARN of the Bedrock AgentCore runtime-ARN secret (the Secret itself, not the runtime ARN value it holds).',
      exportName: `ov-black-${props.envName}-bedrock-agentcore-runtime-arn-arn`,
    });
  }
}
