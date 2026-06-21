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
  readonly databaseUrl: Secret;
  readonly bedrockAgentCoreRuntimeArn: Secret;
  readonly agentTokenSigningSecret: Secret;

  constructor(scope: Construct, id: string, props: SecretsStackProps) {
    super(scope, id, props);

    const namePrefix = `ov-black/${props.envName}`;

    // Secrets Manager rejects empty SecretString values on create, so we seed
    // with a recognizable REPLACE_ME sentinel. apps/api treats any non-real
    // value as unset and fails fast on first use (invite redemption,
    // AgentCore InvokeAgentRuntime).
    const PLACEHOLDER = 'REPLACE_ME';

    this.supabaseServiceRole = new Secret(this, 'SupabaseServiceRole', {
      secretName: `${namePrefix}/supabase-service-role`,
      description:
        'Supabase service role key used by apps/api to sign/verify server-to-server calls (invite redemption, magic-link emit).',
      secretStringValue: SecretValue.unsafePlainText(PLACEHOLDER),
      removalPolicy: props.envName === 'prod' ? RemovalPolicy.RETAIN : RemovalPolicy.DESTROY,
    });

    // Three JSON fields, each extracted into its own env var by ApiStack
    // (apps/api reads flat SUPABASE_URL / SUPABASE_JWT_ISSUER / SUPABASE_JWKS_URL —
    // there is no boot-time secrets-fetch shim, so the shapes must line up). All
    // three keys are seeded (empty) so the ECS json-field extraction resolves even
    // before the operator populates real values.
    this.supabaseJwt = new Secret(this, 'SupabaseJwt', {
      secretName: `${namePrefix}/supabase-jwt`,
      description:
        'Supabase project URL + JWT issuer + JWKS URL consumed by apps/api auth middleware (verify user tokens) and the admin-API auth routes. JSON: {url, issuer, jwks_url}.',
      secretStringValue: SecretValue.unsafePlainText(
        JSON.stringify({ url: '', issuer: '', jwks_url: '' }),
      ),
      removalPolicy: props.envName === 'prod' ? RemovalPolicy.RETAIN : RemovalPolicy.DESTROY,
    });

    // The async SQLAlchemy DSN apps/api connects with (asyncpg driver, Supabase
    // Postgres — D003). Without this the container falls back to its
    // localhost:54322 default and every DB-backed request fails in staging, so it
    // is a hard prerequisite for a functioning deploy. Carries the DB password →
    // NEVER log. Shape:
    //   postgresql+asyncpg://postgres.<ref>:<password>@<pooler-host>:6543/postgres
    this.databaseUrl = new Secret(this, 'DatabaseUrl', {
      secretName: `${namePrefix}/database-url`,
      description:
        'Async SQLAlchemy DSN (postgresql+asyncpg://...) apps/api uses to reach the Supabase Postgres instance. NEVER log this value.',
      secretStringValue: SecretValue.unsafePlainText(PLACEHOLDER),
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
      secretStringValue: SecretValue.unsafePlainText(PLACEHOLDER),
      removalPolicy: props.envName === 'prod' ? RemovalPolicy.RETAIN : RemovalPolicy.DESTROY,
    });

    // HS256 key apps/api uses to sign per-session "agent tokens" minted at
    // POST /sessions. The token authenticates the agent runtime to the
    // backend-only /agent/* endpoints (Dossier + Profile + OSINT context,
    // private fact writes) — surfaces that must never accept a Supabase
    // client JWT. Operator rotates this by overwriting the secret value;
    // apps/api re-reads it on next process start. Use a random 32+ byte
    // value (e.g. `openssl rand -base64 48`).
    this.agentTokenSigningSecret = new Secret(this, 'AgentTokenSigningSecret', {
      secretName: `${namePrefix}/agent-token-signing-secret`,
      description:
        'HS256 signing key for per-session agent tokens. Authenticates the agent runtime to backend-only /agent/* endpoints. NEVER log this value.',
      secretStringValue: SecretValue.unsafePlainText(PLACEHOLDER),
      removalPolicy: props.envName === 'prod' ? RemovalPolicy.RETAIN : RemovalPolicy.DESTROY,
    });

    new CfnOutput(this, 'SupabaseServiceRoleArn', {
      value: this.supabaseServiceRole.secretArn,
      description: 'ARN of the Supabase service-role-key secret.',
      exportName: `ov-black-${props.envName}-supabase-service-role-arn`,
    });

    new CfnOutput(this, 'SupabaseJwtArn', {
      value: this.supabaseJwt.secretArn,
      description: 'ARN of the Supabase URL + JWT issuer + JWKS URL secret.',
      exportName: `ov-black-${props.envName}-supabase-jwt-arn`,
    });

    new CfnOutput(this, 'DatabaseUrlArn', {
      value: this.databaseUrl.secretArn,
      description: 'ARN of the Supabase Postgres DSN secret consumed by apps/api.',
      exportName: `ov-black-${props.envName}-database-url-arn`,
    });

    new CfnOutput(this, 'BedrockAgentCoreRuntimeArnArn', {
      value: this.bedrockAgentCoreRuntimeArn.secretArn,
      description: 'ARN of the Bedrock AgentCore runtime-ARN secret (the Secret itself, not the runtime ARN value it holds).',
      exportName: `ov-black-${props.envName}-bedrock-agentcore-runtime-arn-arn`,
    });

    new CfnOutput(this, 'AgentTokenSigningSecretArn', {
      value: this.agentTokenSigningSecret.secretArn,
      description: 'ARN of the agent-token signing-key secret.',
      exportName: `ov-black-${props.envName}-agent-token-signing-secret-arn`,
    });
  }
}
