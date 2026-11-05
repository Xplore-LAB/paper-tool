#!/usr/bin/env node
// Authorized ScienceDirect download through an existing Chrome and RVPN proxy.
import {createRequire} from 'node:module';
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
const args=process.argv.slice(2);
if(args.includes('--help')||args.includes('-h')){console.log('node browser_pdf.mjs --pii PII --out file.pdf [--cdp http://127.0.0.1:18806] [--proxy http://127.0.0.1:1081]');process.exit(0);}
function option(k,d){const i=args.indexOf(k);return i<0?d:args[i+1];}
const pii=option('--pii',''),out=option('--out','');
if(!/^S\d{16}$/.test(pii)||!out){console.error(JSON.stringify({ok:false,error:'Provide a valid --pii and --out'}));process.exit(2);}
const require=createRequire(import.meta.url);
let chromium;
try{({chromium}=require('playwright-core'));}catch{({chromium}=require('/home/lab434/src/services/literature-browser/node_modules/playwright-core'));}
let browser,context;
try{
 await fs.access(out).then(()=>{throw new Error('Output exists; refusing to overwrite');},()=>{});
 browser=await chromium.connectOverCDP(option('--cdp','http://127.0.0.1:18806'));
 context=await browser.newContext({proxy:{server:option('--proxy','http://127.0.0.1:1081'),bypass:'*.elseviercdn.cn,*.adobedtm.com,*.pendo.io,*.newrelic.com,*.google.com,*.googletagservices.com'},acceptDownloads:true});
 const page=await context.newPage();
 await page.goto('https://www.sciencedirect.com/science/article/pii/'+pii,{waitUntil:'domcontentloaded',timeout:45000});
 const link=page.locator('a').filter({hasText:/View\s*PDF/i}).first();
 await page.waitForFunction(()=>[...document.querySelectorAll('a')].some(a=>/View\s*PDF/i.test(a.innerText)&&a.getAttribute('href')),{},{timeout:30000});
 const popupPromise=page.waitForEvent('popup',{timeout:30000});
 await link.click();const pdfPage=await popupPromise;
 await pdfPage.waitForURL(u=>u.hostname==='pdf.sciencedirectassets.com'&&u.pathname.endsWith('.pdf'),{timeout:45000,waitUntil:'domcontentloaded'});
 const info=await pdfPage.evaluate(async()=>{
  const r=await fetch(location.href,{credentials:'include'});
  if(!r.ok||!(r.headers.get('content-type')||'').includes('application/pdf'))throw new Error('Publisher did not return a PDF: '+r.status);
  const bytes=new Uint8Array(await r.arrayBuffer());
  if(bytes.length>60*1024*1024||new TextDecoder().decode(bytes.slice(0,5))!=='%PDF-')throw new Error('Invalid or oversized PDF');
  window.__paperDownload=bytes;return{bytes:bytes.length};
 });
 await fs.mkdir(path.dirname(path.resolve(out)),{recursive:true});
 const temp=out+'.part',file=await fs.open(temp,'wx'),hash=crypto.createHash('sha256');
 try{for(let i=0;i<info.bytes;i+=32768){const data=await pdfPage.evaluate(i=>btoa(String.fromCharCode(...window.__paperDownload.slice(i,i+32768))),i);const bytes=Buffer.from(data,'base64');await file.write(bytes);hash.update(bytes);}}finally{await file.close();await pdfPage.evaluate(()=>delete window.__paperDownload);}
 await fs.rename(temp,out);
 console.log(JSON.stringify({ok:true,data:{file:path.resolve(out),bytes:info.bytes,sha256:hash.digest('hex'),access:'RVPN + authorized browser',identity:'requires separate title/DOI verification'}}));
}catch(e){console.error(JSON.stringify({ok:false,error:{code:e.name,message:'Browser download failed; inspect the authorized page or local output path'}}));process.exitCode=1;
}finally{if(context)await context.close();if(browser)await browser.close();}
