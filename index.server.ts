import entry from "./server/entry.cjs";

/** Paseo owns startup, reload, disable and removal of this integration. */
export default function contribute() {
  return entry.activate();
}
