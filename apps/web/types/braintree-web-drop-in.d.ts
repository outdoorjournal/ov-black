// Minimal ambient types for braintree-web-drop-in — the package ships no
// type declarations and we only use the create → requestPaymentMethod surface.
declare module "braintree-web-drop-in" {
  export interface Dropin {
    requestPaymentMethod(): Promise<{ nonce: string }>;
    teardown(): Promise<void>;
  }

  export interface DropinCreateOptions {
    authorization: string;
    container: HTMLElement | string;
  }

  export function create(options: DropinCreateOptions): Promise<Dropin>;

  const dropin: { create: typeof create };
  export default dropin;
}
