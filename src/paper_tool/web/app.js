'use strict';
const strings = {
 zh: {brand:'文献直达',eyebrow:'让论文获取更省事',headline:'贴上清单，把论文带回来。',intro:'输入 DOI 或完整参考文献。下载、核验和归档，交给工具处理。',references:'想要哪些论文？',input_hint:'每行一篇，可直接粘贴参考文献清单。',example:'填入示例',import_list:'导入文本清单',limit:'每次最多 200 条',institutional:'使用学校订阅',institution_hint:'可选 ScienceDirect 授权访问，需先在专用浏览器登录。',open_browser:'打开登录浏览器',archive:'同时归档到 Zotero',archive_hint:'只下载无需打开 Zotero。归档需要 Zotero 10+ 开启本地接口。',read_collections:'读取分类',metadata_only:'只存题录，不获取 PDF',connection_settings:'连接设置',zotero_address:'Zotero 本地接口地址',connection_hint:'在 Zotero“设置 → 高级”开启本机通信。首次归档时需在 Zotero 中确认授权。',start:'开始下载',start_metadata:'保存题录',results:'论文到哪一步了？',current_session:'本次打开的任务',empty_title:'论文会出现在这里',empty_hint:'开始后可查看逐篇进度，完成后下载单篇或打包取回。',paper:'论文',status:'状态',file:'文件',download_all:'打包下载 PDF',retry:'补下未完成的论文',saved_to:'本机保存位置：',open_folder:'打开文件夹',privacy:'在本机处理清单，仅向文献来源发送必要请求。',running:'正在处理',completed:'本批任务已完成',partial:'部分完成，还有条目待补',error:'任务需要处理',processed:'已处理',available:'可取回 PDF',working_tip:'按论文逐篇处理；访问文献来源可能需要片刻。',pending_tip:'待补论文可在授权访问就绪后重试。已完成文件会保留。',done_tip:'可取回单篇 PDF，或一次打包下载。',PDF_SAVED:'已下载',PDF_ATTACHED:'已归档',PDF_ALREADY_PRESENT:'附件已确认',METADATA_ONLY:'题录已归档',PDF_PENDING:'全文待补',NEEDS_REVIEW:'需复核',WAITING:'等待处理',archive_pending:'已下载，归档待处理',download:'取回 PDF',empty_references:'请先填入 DOI 或完整参考文献。',invalid_references:'请使用每行一篇的文本清单。',too_many_references:'每批最多 200 条，可分批处理。',invalid_options:'请重新选择下载选项。',choose_collection:'请选择已有 Zotero 分类。',invalid_collection:'分类名称无效，请重新读取分类。',invalid_zotero:'请填写本机 Zotero 接口地址，或本机回环转发地址。',busy:'已有任务在处理，请等它完成。',invalid_request:'请求未能读取，请重试。',connection_failed:'连接失败。归档前请打开 Zotero 并允许本机通信。',browser_unavailable:'未能打开专用浏览器，请检查本机 Chrome 或 Edge。',browser_ready:'请在打开的浏览器中完成机构登录，再开始下载。',nothing_pending:'这批任务没有待补条目。',task_failed:'处理未完成。请检查网络或 Zotero 连接后重试。',not_found:'文件或任务暂不可用，请刷新后重试。',forbidden:'页面连接已失效，请刷新页面。',no_files:'还没有可取回的 PDF。',offline:'连接中断，请确认启动窗口仍在运行。',file_too_large:'文本清单太大，请限制在 128 KB 内。',working:'处理中…',folder_opened:'已请求打开本机保存目录。'},
 en: {brand:'Papers, delivered',eyebrow:'Less hunting. More reading.',headline:'Paste your list. Bring the papers back.',intro:'Start with DOIs or full citations. Let CiteCargo retrieve, verify and file the papers.',references:'Which papers do you need?',input_hint:'One paper per line. Paste a reference list or import a text file.',example:'Try an example',import_list:'Import text list',limit:'Up to 200 entries',institutional:'Use institutional access',institution_hint:'Optional authorized ScienceDirect route. Sign in through the dedicated browser first.',open_browser:'Open login browser',archive:'Also file in Zotero',archive_hint:'Downloads need no Zotero. Archival requires Zotero 10+ with its local API enabled.',choose_collection:'Select an existing collection',read_collections:'Load collections',metadata_only:'Save references only, without PDFs',connection_settings:'Connection settings',zotero_address:'Local Zotero API address',connection_hint:'Enable local communication in Zotero Settings → Advanced. Approve the first write in Zotero.',start:'Start downloading',start_metadata:'Save references',results:'Where are your papers?',current_session:'Tasks in this session',empty_title:'Your papers will appear here',empty_hint:'Follow each paper, then retrieve individual PDFs or download them together.',paper:'Paper',status:'Status',file:'File',download_all:'Download PDFs as ZIP',retry:'Retry unfinished papers',saved_to:'Local save folder: ',open_folder:'Open folder',privacy:'Lists are processed locally. Only necessary requests go to paper sources.',running:'Working through the list',completed:'This batch is complete',partial:'Some entries still need attention',error:'This task needs attention',processed:'Processed',available:'PDFs available',working_tip:'Papers are processed one at a time. Source requests may take a moment.',pending_tip:'Retry missing papers when access is ready. Completed files are retained.',done_tip:'Retrieve a PDF or download the batch as a ZIP.',PDF_SAVED:'Downloaded',PDF_ATTACHED:'Filed in Zotero',PDF_ALREADY_PRESENT:'Attachment confirmed',METADATA_ONLY:'Reference filed',PDF_PENDING:'Full text pending',NEEDS_REVIEW:'Needs review',WAITING:'Waiting',archive_pending:'Downloaded; archival pending',download:'Get PDF',empty_references:'Enter at least one DOI or full citation.',invalid_references:'Use a text list with one paper per line.',too_many_references:'Use at most 200 entries per batch.',invalid_options:'Please select the download options again.',invalid_collection:'Reload and select an existing collection.',invalid_zotero:'Use the local Zotero API or a loopback forwarding address.',busy:'A task is running. Please wait for it to finish.',invalid_request:'The request could not be read. Please retry.',connection_failed:'Connection failed. Open Zotero and enable local communication before archival.',browser_unavailable:'The dedicated browser could not start. Check Chrome or Edge.',browser_ready:'Complete the institutional login in the opened browser, then start downloading.',nothing_pending:'There are no unfinished entries in this batch.',task_failed:'Processing did not complete. Check the network or Zotero connection and retry.',not_found:'This task or file is unavailable. Refresh and retry.',forbidden:'The page connection expired. Refresh the page.',no_files:'No PDF is ready yet.',offline:'Connection interrupted. Keep the launcher window running.',file_too_large:'Keep the text list below 128 KB.',working:'Working…',folder_opened:'Requested opening the local save folder.'}
};
const $=id=>document.getElementById(id);
let language=new URLSearchParams(location.search).get('lang')==='en'?'en':'zh';
let settings,active=null,timer=null,refreshing=false;
const t=key=>strings[language][key]||strings.en[key]||key;
function notice(key){$('notice').textContent=key?t(key):'';}
function localize(){
 document.documentElement.lang=language==='zh'?'zh-CN':'en';
 document.title=language==='zh'?'CiteCargo · 文献直达':'CiteCargo';
 document.querySelectorAll('[data-i18n]').forEach(e=>e.textContent=t(e.dataset.i18n));
 $('language').textContent=language==='zh'?'English':'中文';
 $('collection').setAttribute('aria-label',t('choose_collection'));$('history').setAttribute('aria-label',t('current_session'));
 $('start').textContent=t($('metadata-only').checked?'start_metadata':'start');
 const emptyCollection=$('collection').querySelector('option[value=""]');if(emptyCollection)emptyCollection.textContent=t('choose_collection');
 const emptyHistory=$('history').querySelector('option[value=""]');if(emptyHistory)emptyHistory.textContent=t('current_session');
}
async function api(path,data){
 let r;
 try{r=await fetch(path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-CiteCargo-Token':settings.token},body:JSON.stringify(data)});}catch{throw new Error('offline');}
 const body=await r.json();if(!r.ok)throw new Error(body.error||'task_failed');return body;
}
function chooseTask(id){active=id;clearTimeout(timer);poll();}
async function poll(){
 clearTimeout(timer);
 if(!active)return;
 const selected=active;
 try{const job=await api('/api/jobs/'+selected);if(active!==selected)return;render(job);if(job.state==='running')timer=setTimeout(poll,1200);else await history();}catch(e){notice(e.message);}
}
function render(job){
 $('empty').hidden=true;$('task').hidden=false;
 $('task-state').textContent=t(job.state);$('counts').textContent=t('processed')+' '+job.processed+'/'+job.total+' · '+t('available')+' '+job.available;
 $('progress').max=job.total||1;$('progress').value=job.processed;
 $('task-tip').textContent=t(job.state==='running'?'working_tip':job.state==='completed'?'done_tip':'pending_tip');
 if(job.error)notice(job.error);
 $('rows').replaceChildren();
 job.results.forEach((row,index)=>{
  const tr=document.createElement('tr'),title=document.createElement('td'),status=document.createElement('td'),file=document.createElement('td');
  title.textContent=row.title;
  if(row.doi){const id=document.createElement('span');id.className='doi';id.textContent=row.doi;title.appendChild(id);}
  status.textContent=t(row.archive_pending?'archive_pending':row.status);
  status.className=['PDF_SAVED','PDF_ATTACHED','PDF_ALREADY_PRESENT','METADATA_ONLY'].includes(row.status)&&!row.archive_pending?'good':'pending';
  if(row.pdf){const a=document.createElement('a');a.href='/api/jobs/'+job.id+'/file/'+index;a.textContent=t('download');file.appendChild(a);}else file.textContent='—';
  tr.append(title,status,file);$('rows').appendChild(tr);
 });
 $('zip').hidden=job.available===0;$('zip').href='/api/jobs/'+job.id+'/zip';
 $('retry').hidden=!['partial','error'].includes(job.state);
 $('start').disabled=job.state==='running';
}
async function history(){
 if(refreshing)return;refreshing=true;
 try{const result=await api('/api/jobs');$('history').replaceChildren();
  if(!result.jobs.length){const o=document.createElement('option');o.textContent=t('current_session');o.value='';$('history').appendChild(o);}
  result.jobs.forEach(j=>{const o=document.createElement('option');o.value=j.id;o.textContent=j.created+' · '+j.total;o.selected=j.id===active;$('history').appendChild(o);});
  if(!active&&result.jobs.length)chooseTask(result.jobs[0].id);
 }catch(e){notice(e.message);}finally{refreshing=false;}
}
$('language').addEventListener('click',()=>{language=language==='zh'?'en':'zh';localize();notice('');if(active)poll();});
$('example').addEventListener('click',()=>{$('references').value='10.1371/journal.pone.0000308';notice('');});
$('institutional').addEventListener('change',()=>{$('browser').hidden=!$('institutional').checked;});
$('zotero').addEventListener('change',()=>{$('archive-options').hidden=!$('zotero').checked;if(!$('zotero').checked)$('metadata-only').checked=false;localize();});
$('metadata-only').addEventListener('change',localize);
$('history').addEventListener('change',()=>{notice('');chooseTask($('history').value);});
$('input-file').addEventListener('change',async()=>{try{const f=$('input-file').files[0];if(!f)return;if(f.size>128*1024)throw new Error('file_too_large');const bytes=await f.arrayBuffer();let text;try{text=new TextDecoder('utf-8',{fatal:true}).decode(bytes);}catch{text=new TextDecoder('gb18030').decode(bytes);}$('references').value=text;notice('');}catch(e){notice(e.message);}});
$('collections').addEventListener('click',async()=>{const button=$('collections');button.disabled=true;notice('');try{const result=await api('/api/collections',{zotero_base:$('zotero-base').value});$('collection').replaceChildren();const empty=document.createElement('option');empty.value='';empty.textContent=t('choose_collection');$('collection').appendChild(empty);result.collections.forEach(c=>{const o=document.createElement('option');o.value=c.path;o.textContent=c.path;$('collection').appendChild(o);});}catch(e){notice(e.message);}finally{button.disabled=false;}});
$('browser').addEventListener('click',async()=>{$('browser').disabled=true;notice('');try{const r=await api('/api/browser',{});notice(r.ok?'browser_ready':r.error);}catch(e){notice(e.message);}finally{$('browser').disabled=false;}});
$('folder').addEventListener('click',async()=>{try{await api('/api/folder',{});notice('folder_opened');}catch(e){notice(e.message);}});
$('start').addEventListener('click',async()=>{notice('');$('start').disabled=true;try{const r=await api('/api/jobs',{references:$('references').value,zotero:$('zotero').checked,institutional:$('institutional').checked,metadata_only:$('metadata-only').checked,collection:$('collection').value,zotero_base:$('zotero-base').value});chooseTask(r.id);await history();}catch(e){notice(e.message);$('start').disabled=false;}});
$('retry').addEventListener('click',async()=>{notice('');$('retry').disabled=true;try{const r=await api('/api/jobs/'+active+'/retry',{institutional:$('institutional').checked});chooseTask(r.id);await history();}catch(e){notice(e.message);}finally{$('retry').disabled=false;}});
(async()=>{localize();try{settings=await api('/api/settings');$('save-path').textContent=settings.folder;$('zotero-base').value=settings.zotero_base;$('version').textContent='CiteCargo '+settings.version;await history();}catch(e){notice(e.message);$('start').disabled=true;}})();
