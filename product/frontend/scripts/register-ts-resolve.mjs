// Registers the extensionless-TS resolve hook for plain-node test runs.
import { register } from 'node:module';
register('./ts-resolve-hook.mjs', import.meta.url);