import { defineConfig } from 'vite';
export default defineConfig({server:{proxy:{'/api':{target:'https://climate-evidence-api.jimmycai.workers.dev',changeOrigin:true,configure(proxy){proxy.on('proxyReq',req=>req.removeHeader('origin'));}}}}});
