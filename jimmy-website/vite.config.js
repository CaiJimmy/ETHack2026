import { defineConfig } from 'vite';
export default defineConfig({base:'/app/',server:{proxy:{'/api':{target:'https://climate-evidence-api.jimmycai.workers.dev',changeOrigin:true,configure(proxy){proxy.on('proxyReq',req=>req.removeHeader('origin'));}}}}});
