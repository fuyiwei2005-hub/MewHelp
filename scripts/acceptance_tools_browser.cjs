const {chromium}=require(process.env.CODEX_PLAYWRIGHT||'playwright');
const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1365,height:900}});
 page.setDefaultTimeout(90000);
 const checks={},ids={},errors=[];let confirmations=0;
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(r.url().endsWith('/workflow/ticket-preview')&&r.method()==='POST')confirmations++;});
 page.on('dialog',dialog=>dialog.accept());
 const idle=()=>page.waitForFunction(()=>!document.querySelector('#new-chat').disabled);
 async function send(text){await page.locator('#message-input').fill(text);await page.locator('#send').click();await idle();}
 async function cid(){return await page.evaluate(()=>JSON.parse(sessionStorage.getItem('care.chat')).cid);}
 async function preview(){await page.waitForFunction(()=>{const b=document.querySelector('[data-ticket-decision="confirm"]');return b&&!b.disabled;});}
 async function fresh(){await page.locator('#new-chat').click();}
 try{
  await page.goto(process.env.CHAT_URL||'http://127.0.0.1:18000');
  await send('帮我建个工单');
  checks.bare_asks_description=await page.locator('.ticket-preview').count()===0&&/具体|描述|问题/.test(await page.locator('.assistant .bubble').last().textContent());
  await send('演示饮水机不出水，清理水泵后仍未恢复');await preview();ids.confirm=await cid();
  checks.preview_shows_user_facts=(await page.locator('.ticket-preview').last().textContent()).includes('演示饮水机不出水，清理水泵后仍未恢复');
  await page.locator('[data-ticket-decision="confirm"]').click();
  checks.locks_on_first_click=await page.locator('[data-ticket-decision="confirm"]').isDisabled()&&await page.locator('[data-ticket-decision="cancel"]').isDisabled();
  await page.locator('[data-ticket-decision="confirm"]').evaluate(el=>el.click());
  await idle();
  checks.confirmed_receipt=/工单号：T[A-Z0-9]+/.test(await page.locator('.ticket-preview-receipt').last().textContent());
  checks.one_confirmation_request=confirmations===1;
  await page.reload();await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('会话已恢复'));
  checks.reload_keeps_ticket_number=/T[A-Z0-9]{10,}/.test(await page.locator('#messages').textContent());
  await fresh();await send('帮我建工单，演示摄像头反复离线');await preview();ids.cancel=await cid();
  await page.locator('[data-ticket-decision="cancel"]').click();await idle();
  checks.cancelled_card=(await page.locator('.ticket-preview-state').last().textContent())==='已取消';
  checks.cancel_locked=await page.locator('[data-ticket-decision="confirm"]').isDisabled();
  await fresh();await send('帮我建工单，演示杯子破损');await preview();ids.ignored=await cid();
  await send('你好');
  checks.keep_chat_without_confirm=(await page.locator('.ticket-preview-state').last().textContent())==='已失效'&&(await page.locator('.assistant .bubble').last().textContent()).includes('客服小猫');
  await fresh();await send('帮我建工单，演示喂食器反复卡粮');await preview();ids.refresh=await cid();
  await page.reload();await preview();
  checks.pending_restored_after_reload=(await page.locator('.ticket-preview').count())===1;
  await page.screenshot({path:'artifacts/ch08-ticket-preview-desktop.png',fullPage:true,animations:'disabled'});
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:'artifacts/ch08-ticket-preview-mobile.png',fullPage:true,animations:'disabled'});
  checks.mobile_preview_no_overflow=await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1);
  await page.locator('[data-ticket-decision="cancel"]').click();await idle();
  await page.setViewportSize({width:1365,height:900});
  await fresh();await send('我要投诉');ids.complaint=await cid();
  checks.complaint_two_independent_buttons=await page.getByRole('button',{name:'转人工',exact:true}).count()===1&&await page.getByRole('button',{name:'建工单',exact:true}).count()===1;
  await page.getByRole('button',{name:'转人工',exact:true}).click();
  checks.handoff_does_not_disable_ticket=await page.getByRole('button',{name:'建工单',exact:true}).isEnabled();
  await page.getByRole('button',{name:'建工单',exact:true}).click();await idle();
  checks.old_button_creates_receipt=(await page.locator('.workflow-receipt').last().textContent()).includes('工单已创建：T');
  checks.no_page_errors=errors.length===0;
  const report={checks,ids,errors,confirmations};fs.writeFileSync('docs/reports/ch08-browser.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
  if(!Object.values(checks).every(Boolean))process.exitCode=1;
 }catch(error){fs.writeFileSync('docs/reports/ch08-browser.json',JSON.stringify({checks,ids,errors,error:String(error)},null,2));await page.screenshot({path:'artifacts/ch08-browser-failed.png',fullPage:true});throw error;}
 finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
