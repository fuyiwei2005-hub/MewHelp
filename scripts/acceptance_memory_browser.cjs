// UI acceptance with the installed Edge and bundled Playwright; no app data leaves localhost.
const {chromium}=require(process.env.CODEX_PLAYWRIGHT || 'playwright');
const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1365,height:900},reducedMotion:'no-preference'});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));const checks={};
 async function send(text){await page.locator('#message-input').fill(text);await page.locator('#send').click();await page.waitForFunction(()=>!document.querySelector('#new-chat').disabled&&document.querySelectorAll('.assistant .bubble').length>0);}
 try{
  await page.goto(process.env.CHAT_URL||'http://127.0.0.1:18000');
  await send('你好');
  const first=await page.evaluate(()=>JSON.parse(sessionStorage.getItem('care.chat')).cid);
  checks.first_reply=(await page.locator('.assistant .bubble').last().textContent()).length>0;
  await page.locator('#new-chat').click();checks.new_chat_clears_view=await page.locator('.message').count()===0;
  await send('谢谢');const second=await page.evaluate(()=>JSON.parse(sessionStorage.getItem('care.chat')).cid);
  await page.waitForSelector('[data-conversation-id="'+first+'"]');
  checks.two_conversations=first!==second;
  await page.locator('[data-conversation-id="'+first+'"]').click();
  await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('会话已恢复'));
  checks.old_raw_restored=(await page.locator('.user .bubble').first().textContent())==='你好';
  await send('再见');checks.continue_old=(await page.locator('.user .bubble').count())===2;
  await page.reload();await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('会话已恢复'));
  checks.refresh_full_reload=(await page.locator('.user .bubble').count())===2;
  checks.sidebar_scroll_contained=await page.evaluate(()=>document.documentElement.scrollHeight<=window.innerHeight+2);
  await page.screenshot({path:'artifacts/ch07-browser-desktop.png',fullPage:true,animations:'disabled'});
  await page.route('**/api/conversations?*',route=>route.abort());
  await page.locator('#new-chat').click();await send('你好');checks.sidebar_failure_does_not_block=await page.locator('.assistant .bubble').count()===1;
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:'artifacts/ch07-browser-mobile.png',fullPage:true,animations:'disabled'});
  checks.mobile_switch_visible=await page.locator('#mobile-conversations').isVisible();checks.no_script_errors=errors.length===0;
  const report={checks,errors,conversations:{first,second}};fs.writeFileSync('docs/reports/ch07-browser.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
  if(!Object.values(checks).every(Boolean))process.exitCode=1;
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
