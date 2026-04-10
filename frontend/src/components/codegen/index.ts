/**
 * components/codegen/index.ts
 *
 * Public exports for the codegen module.
 *
 * Usage in app router:
 *   import { CodegenPanel, CodegenPopout } from "./components/codegen";
 *
 *   // Docked tab
 *   <Route path="/codegen" element={<CodegenPanel />} />
 *
 *   // Popout window
 *   <Route path="/codegen-popout" element={<CodegenPopout />} />
 */
export { CodegenPanel } from "./CodegenPanel";
export { CodegenPopout } from "./CodegenPopout";
export { CodeBlock } from "./CodeBlock";
