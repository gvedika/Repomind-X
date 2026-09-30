declare module "legacy-payments" {
  export function charge(amount: number): Promise<string>;
}
