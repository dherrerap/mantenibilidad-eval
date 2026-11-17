import fs from 'node:fs';
import react from '@vitejs/plugin-react';
fs.writeFileSync(new URL('./EXECUTED.txt', import.meta.url), 'vite.config.js was executed');
export default { plugins: [react()] };
