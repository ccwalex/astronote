// Dev-only node resolve hook: lets the plain-node test harnesses import
// extensionless relative TS modules (matches the bundler-style imports used
// across src/). Registered from register-ts-resolve.mjs.
export async function resolve(specifier, context, next) {
  try {
    return await next(specifier, context);
  } catch (err) {
    if (
      err?.code === 'ERR_MODULE_NOT_FOUND' &&
      !specifier.endsWith('.ts') &&
      (specifier.startsWith('./') || specifier.startsWith('../'))
    ) {
      return next(`${specifier}.ts`, context);
    }
    throw err;
  }
}