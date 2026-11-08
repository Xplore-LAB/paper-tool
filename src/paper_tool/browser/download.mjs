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
if(!/^S[A-Z0-9]{16}$/.test(pii)||!out){console.error(JSON.stringify({ok:false,error:{code:'InvalidArguments',message:'Provide a valid --pii and --out'}}));process.exit(2);}
const require=createRequire(import.meta.url);
let chromium;
try{
 ({chromium}=require(process.env.PLAYWRIGHT_CORE_PATH||'playwright-core'));
}catch{
 // A wheel may live outside the project that contains node_modules.
 try{({chromium}=createRequire(path.resolve(process.cwd(),'package.json'))('playwright-core'));}catch{}
 // Optional override for a non-standard local install, set by the caller.
 if(process.env.PLAYWRIGHT_CORE_PATH){
  try{({chromium}=require(process.env.PLAYWRIGHT_CORE_PATH));}catch{}
 }
 if(!chromium){
  console.error(JSON.stringify({ok:false,error:{code:'MissingDependency',message:'playwright-core not found. Run "npm install playwright-core" in the project root.'}}));
  process.exit(2);
 }
}
let browser,context,activePage,tempPath,stage='connect',ownsContext=false;
try{
 await fs.access(out).then(()=>{throw new Error('Output exists; refusing to overwrite');},()=>{});
 browser=await chromium.connectOverCDP(option('--cdp','http://127.0.0.1:18806'));
 const proxyServer=option('--proxy','http://127.0.0.1:1081');
 ownsContext=proxyServer!=='direct';
 context=ownsContext?await browser.newContext({proxy:{server:proxyServer,bypass:'*.elseviercdn.cn,*.adobedtm.com,*.pendo.io,*.newrelic.com,*.google.com,*.googletagservices.com'},acceptDownloads:true}):browser.contexts()[0];
 const page=await context.newPage();
 activePage=page;stage='article-navigation';
 await page.goto('https://www.sciencedirect.com/science/article/pii/'+pii,{waitUntil:'domcontentloaded',timeout:45000});
 const link=page.locator('a').filter({hasText:/View\s*PDF/i}).first();
 stage='find-view-pdf';
 await page.waitForFunction(()=>[...document.querySelectorAll('a')].some(a=>/View\s*PDF/i.test(a.innerText)&&a.getAttribute('href')),{},{timeout:30000});
 const popupPromise=page.waitForEvent('popup',{timeout:30000});
 stage='open-pdf-popup';
 await link.click();const pdfPage=await popupPromise;
 activePage=pdfPage;stage='pdf-navigation';
 await pdfPage.waitForURL(u=>u.hostname==='pdf.sciencedirectassets.com'&&u.pathname.endsWith('.pdf'),{timeout:45000,waitUntil:'domcontentloaded'});
 const info=await pdfPage.evaluate(async()=>{
  const r=await fetch(location.href,{credentials:'include'});
  if(!r.ok||!(r.headers.get('content-type')||'').includes('application/pdf'))throw new Error('Publisher did not return a PDF: '+r.status);
  const bytes=new Uint8Array(await r.arrayBuffer());
  if(bytes.length>60*1024*1024||new TextDecoder().decode(bytes.slice(0,5))!=='%PDF-')throw new Error('Invalid or oversized PDF');
  window.__paperDownload=bytes;return{bytes:bytes.length};
 });
 await fs.mkdir(path.dirname(path.resolve(out)),{recursive:true});
 tempPath=out+'.'+crypto.randomUUID()+'.part';
 const file=await fs.open(tempPath,'wx'),hash=crypto.createHash('sha256');
 try{for(let i=0;i<info.bytes;i+=32768){const data=await pdfPage.evaluate(i=>btoa(String.fromCharCode(...window.__paperDownload.slice(i,i+32768))),i);const bytes=Buffer.from(data,'base64');await file.write(bytes);hash.update(bytes);}}finally{await file.close();await pdfPage.evaluate(()=>delete window.__paperDownload);}
 // Publish without replacement, even if another process created out meanwhile.
 await fs.link(tempPath,out);
 await fs.unlink(tempPath);tempPath=undefined;
 console.log(JSON.stringify({ok:true,data:{file:path.resolve(out),bytes:info.bytes,sha256:hash.digest('hex'),access:'RVPN + authorized browser',identity:'requires separate title/DOI verification'}}));
}catch(e){console.error(JSON.stringify({ok:false,error:{code:e.name,message:'Browser download failed at '+stage+'; page title: '+(activePage?await activePage.title().catch(()=> 'unavailable'):'unavailable')}}));process.exitCode=1;
}finally{if(tempPath)await fs.unlink(tempPath).catch(()=>{});if(context&&ownsContext)await context.close();if(browser)await browser.close();}
