/** Module customization hooks of no_exec_guard.mjs: an ESM import of a file under the guarded root fails before it is evaluated. */
let root = null;

export async function initialize(data) {
  root = data && data.root;
}

export async function load(url, context, nextLoad) {
  if (root && url.toLowerCase().startsWith(root.toLowerCase())) {
    const e = new Error(`no_exec_guard: refused to execute ${url}`);
    e.code = "NO_EXEC_GUARD";
    throw e;
  }
  return nextLoad(url, context);
}
