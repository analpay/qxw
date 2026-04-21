"""Webtool 开发者工具 HTTP 服务

提供一组开发者常用的 Web 小工具，所有逻辑均在单页应用中通过前端调用后端 API：
- 文本对比 / JSON 格式化 / 时间戳转换
- 哈希 / HMAC / AES / DES / 3DES / RSA / Ed25519 / 证书解析
- URL 编解码 / Base64 编解码
"""

from __future__ import annotations

import base64 as b64_mod
import difflib
import hashlib
import hmac as hmac_mod
import json
import os
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from qxw import __version__
from qxw.library.base.logger import get_logger

logger = get_logger("qxw.serve.webtool")


# ============================================================
# HTML 页面模板
# ============================================================

_HTML_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QXW WebTool</title>
<style>
:root {
  --c1: #6366f1; --c1h: #4f46e5; --c1l: #eef2ff;
  --bg: #f1f5f9; --hd: #0f172a; --card: #fff;
  --bd: #e2e8f0; --tx: #0f172a; --tm: #64748b;
  --ok: #22c55e; --err: #ef4444;
  --mono: 'SF Mono',SFMono-Regular,Menlo,Consolas,monospace;
  --r: 10px;
  --sh: 0 1px 3px rgba(0,0,0,.06),0 1px 2px rgba(0,0,0,.04);
  --shm: 0 4px 6px rgba(0,0,0,.07),0 2px 4px rgba(0,0,0,.04);
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body {
  font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',
    'Noto Sans SC','PingFang SC',sans-serif;
  background: var(--bg); color: var(--tx); line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}
.header {
  background: linear-gradient(135deg,var(--hd),#1e293b 80%);
  padding: 0 28px; display: flex; align-items: center;
  gap: 36px; position: sticky; top: 0; z-index: 100;
  box-shadow: 0 4px 16px rgba(0,0,0,.3);
}
.brand { color: #fff; font-size: 17px; font-weight: 700;
  padding: 18px 0; white-space: nowrap; letter-spacing: -.01em; }
.brand small { font-weight: 400; font-size: 11px;
  opacity: .45; margin-left: 8px; }
.tabs { display: flex; gap: 2px; overflow-x: auto;
  scrollbar-width: none; }
.tabs::-webkit-scrollbar { display: none; }
.tab {
  background: none; border: none; color: rgba(255,255,255,.45);
  padding: 18px 18px; cursor: pointer; font-size: 13.5px;
  font-weight: 500; white-space: nowrap;
  border-bottom: 2.5px solid transparent;
  transition: all .2s ease;
}
.tab:hover { color: rgba(255,255,255,.8); }
.tab.active { color: #fff; border-bottom-color: var(--c1);
  text-shadow: 0 0 14px rgba(99,102,241,.5); }
.content { max-width: 1200px; margin: 28px auto; padding: 0 28px; }
.panel { display: none; }
.panel.active { display: block; animation: fadeIn .22s ease; }
@keyframes fadeIn {
  from{opacity:0;transform:translateY(5px)}
  to{opacity:1;transform:none}
}
.panel > h2 { font-size: 18px; font-weight: 700;
  margin-bottom: 20px; letter-spacing: -.02em; }
label { display: block; font-size: 11.5px; font-weight: 600;
  color: var(--tm); margin-bottom: 6px;
  text-transform: uppercase; letter-spacing: .05em; }
textarea,input[type="text"],select {
  width: 100%; padding: 11px 14px;
  border: 1.5px solid var(--bd); border-radius: var(--r);
  font-family: var(--mono); font-size: 13px;
  background: var(--card); color: var(--tx);
  resize: vertical; transition: all .2s ease;
  box-shadow: var(--sh);
}
textarea:focus,input[type="text"]:focus,select:focus {
  outline: none; border-color: var(--c1);
  box-shadow: 0 0 0 3px rgba(99,102,241,.12),var(--sh);
}
textarea[readonly] { background: #f8fafc; border-style: dashed; }
textarea::placeholder,input::placeholder {
  color: #94a3b8; font-weight: 400; }
textarea::-webkit-scrollbar { width: 6px; }
textarea::-webkit-scrollbar-thumb {
  background: #cbd5e1; border-radius: 3px; }
textarea::-webkit-scrollbar-thumb:hover { background: #94a3b8; }
select { width: auto; min-width: 120px; cursor: pointer; }
.fr { margin-bottom: 14px; position: relative; }
.fg { background: var(--card); border: 1.5px solid var(--bd);
  border-radius: var(--r); padding: 20px;
  margin-bottom: 14px; box-shadow: var(--sh); }
.acts { display: flex; gap: 8px; margin: 16px 0;
  flex-wrap: wrap; align-items: center; }
.btn {
  padding: 9px 22px; border: 1.5px solid var(--bd);
  border-radius: var(--r); cursor: pointer; font-size: 13px;
  font-weight: 600; background: var(--card); color: var(--tx);
  transition: all .15s ease; box-shadow: var(--sh);
  user-select: none;
}
.btn:hover { background: #f8fafc; box-shadow: var(--shm);
  transform: translateY(-1px); }
.btn:active { transform: none; box-shadow: var(--sh); }
.bp { background: var(--c1); color: #fff; border-color: var(--c1);
  box-shadow: 0 2px 4px rgba(99,102,241,.3); }
.bp:hover { background: var(--c1h); border-color: var(--c1h);
  box-shadow: 0 4px 10px rgba(99,102,241,.35);
  transform: translateY(-1px); }
.bp:active { transform: none;
  box-shadow: 0 1px 2px rgba(99,102,241,.2); }
.bc { padding: 6px 14px; font-size: 12px; border-radius: 8px;
  font-weight: 500; color: var(--tm);
  background: var(--bg); border-color: transparent; }
.bc:hover { color: var(--tx); background: #e2e8f0;
  transform: none; box-shadow: none; }
.diff-wrap { display: grid;
  grid-template-columns: 1fr 1fr; gap: 16px; }
#diff-result {
  background: var(--card); border: 1.5px solid var(--bd);
  border-radius: var(--r); padding: 18px;
  font-family: var(--mono); font-size: 13px; line-height: 1.7;
  white-space: pre-wrap; word-break: break-all;
  overflow-x: auto; min-height: 60px; box-shadow: var(--sh);
}
.da { color: #166534; background: #dcfce7;
  display: inline-block; width: 100%;
  padding: 1px 6px; border-radius: 3px; }
.dd { color: #991b1b; background: #fee2e2;
  display: inline-block; width: 100%;
  padding: 1px 6px; border-radius: 3px; }
.dr { color: #7c3aed; font-weight: 500; }
.dh { color: #1d4ed8; font-weight: 700; }
.ts-bar {
  background: linear-gradient(135deg,var(--c1l),#fff 70%);
  border: 1.5px solid #c7d2fe; border-radius: var(--r);
  padding: 14px 20px; margin-bottom: 16px; display: flex;
  align-items: center; gap: 14px; font-size: 14px;
  flex-wrap: wrap; box-shadow: var(--sh);
}
.ts-bar code { font-family: var(--mono); font-weight: 800;
  color: var(--c1h); font-size: 20px; }
.rbox {
  background: var(--card); border: 1.5px solid var(--bd);
  border-radius: var(--r); padding: 18px;
  font-family: var(--mono); font-size: 13px;
  box-shadow: var(--sh);
}
.rbox div { padding: 6px 0;
  border-bottom: 1px solid #f1f5f9; }
.rbox div:last-child { border-bottom: none; }
.rbox code { background: var(--c1l); color: var(--c1h);
  padding: 3px 8px; border-radius: 6px;
  font-size: 13px; font-weight: 600; }
.stabs { display: flex; gap: 4px; padding: 4px;
  background: #e8ecf1; border-radius: var(--r);
  margin-bottom: 20px; }
.stab {
  background: none; border: none; border-radius: 7px;
  padding: 8px 16px; cursor: pointer; font-size: 13px;
  font-weight: 500; color: var(--tm); transition: all .2s;
}
.stab:hover { color: var(--tx);
  background: rgba(255,255,255,.5); }
.stab.active { color: var(--c1h); background: var(--card);
  box-shadow: 0 1px 4px rgba(0,0,0,.08); font-weight: 600; }
.sp { display: none; }
.sp.active { display: block; animation: fadeIn .15s ease; }
.err { color: var(--err); font-weight: 500; }
.inline { display: flex; gap: 10px; align-items: center; }
.inline select,.inline .btn { flex-shrink: 0; }
</style>
</head>
<body>
<div class="header">
  <div class="brand">🛠️ QXW WebTool<small>__VERSION__</small></div>
  <nav class="tabs">
    <button class="tab active" data-tab="diff">文本对比</button>
    <button class="tab" data-tab="json">JSON 格式化</button>
    <button class="tab" data-tab="ts">时间戳转换</button>
    <button class="tab" data-tab="crypto">加解密</button>
    <button class="tab" data-tab="url">URL 编解码</button>
    <button class="tab" data-tab="b64">Base64 编解码</button>
  </nav>
</div>
<div class="content">

<!-- ===== 文本对比 ===== -->
<div id="p-diff" class="panel active">
  <h2>文本对比</h2>
  <div class="diff-wrap">
    <div class="fr"><label>文本 A</label><textarea id="d-t1" rows="14" placeholder="输入第一段文本..."></textarea></div>
    <div class="fr"><label>文本 B</label><textarea id="d-t2" rows="14" placeholder="输入第二段文本..."></textarea></div>
  </div>
  <div class="acts">
    <button class="btn bp" onclick="doDiff()">对比</button>
    <button class="btn" onclick="Q('d-t1').value=Q('d-t2').value='';Q('diff-result').innerHTML=''">清空</button>
  </div>
  <div id="diff-result"></div>
</div>

<!-- ===== JSON 格式化 ===== -->
<div id="p-json" class="panel">
  <h2>JSON 格式化</h2>
  <div class="acts">
    <button class="btn bp" onclick="doJson('format')">格式化</button>
    <button class="btn bp" onclick="doJson('minify')">压缩</button>
    <button class="btn bp" onclick="doJson('validate')">校验</button>
    <button class="btn bp" onclick="doJson('escape')">转义</button>
    <button class="btn bp" onclick="doJson('unescape')">去转义</button>
    <button class="btn bc" onclick="cp('j-out')">复制结果</button>
  </div>
  <div class="diff-wrap">
    <div class="fr"><label>输入</label>
      <textarea id="j-in" rows="20" placeholder="输入 JSON 文本..."></textarea></div>
    <div class="fr"><label>结果</label>
      <textarea id="j-out" rows="20" readonly placeholder="输出..."></textarea></div>
  </div>
</div>

<!-- ===== 时间戳转换 ===== -->
<div id="p-ts" class="panel">
  <h2>时间戳转换</h2>
  <div class="ts-bar">
    <span>当前时间戳：</span><code id="ts-now">-</code>
    <span id="ts-dt">-</span>
  </div>
  <div class="fr">
    <label>输入时间戳或日期时间</label>
    <input id="ts-in" type="text" placeholder="如: 1700000000 / 1700000000000 / 2023-11-14 22:13:20">
  </div>
  <div class="acts">
    <button class="btn bp" onclick="doTs('to_datetime')">时间戳 → 日期</button>
    <button class="btn bp" onclick="doTs('to_timestamp')">日期 → 时间戳</button>
    <button class="btn bp" onclick="doTs('now')">获取当前</button>
  </div>
  <div id="ts-result" class="rbox" style="display:none"></div>
</div>

<!-- ===== 加解密 ===== -->
<div id="p-crypto" class="panel">
  <h2>加解密</h2>
  <div class="stabs">
    <button class="stab active" data-st="hash">哈希</button>
    <button class="stab" data-st="hmac">HMAC</button>
    <button class="stab" data-st="aes">AES</button>
    <button class="stab" data-st="des">DES / 3DES</button>
    <button class="stab" data-st="rsa">RSA</button>
    <button class="stab" data-st="ed">Ed25519</button>
    <button class="stab" data-st="cert">证书解析</button>
  </div>

  <!-- 哈希 -->
  <div id="sp-hash" class="sp active">
    <div class="fr"><label>输入文本</label>
      <textarea id="h-in" rows="4" placeholder="输入要计算哈希的文本..."></textarea></div>
    <div class="acts">
      <button class="btn bp" onclick="doHash('md5')">MD5</button>
      <button class="btn bp" onclick="doHash('sha1')">SHA1</button>
      <button class="btn bp" onclick="doHash('sha256')">SHA256</button>
      <button class="btn bp" onclick="doHash('sha512')">SHA512</button>
    </div>
    <div class="fr inline"><input id="h-out" type="text" readonly placeholder="哈希结果...">
      <button class="btn bc" onclick="cp('h-out')">复制</button></div>
  </div>

  <!-- HMAC -->
  <div id="sp-hmac" class="sp">
    <div class="fr"><label>输入文本</label><textarea id="hm-in" rows="4" placeholder="输入文本..."></textarea></div>
    <div class="fr"><label>密钥</label><input id="hm-key" type="text" placeholder="输入 HMAC 密钥..."></div>
    <div class="acts">
      <button class="btn bp" onclick="doHmac('hmac-sha256')">HMAC-SHA256</button>
      <button class="btn bp" onclick="doHmac('hmac-sha512')">HMAC-SHA512</button>
    </div>
    <div class="fr inline"><input id="hm-out" type="text" readonly placeholder="HMAC 结果...">
      <button class="btn bc" onclick="cp('hm-out')">复制</button></div>
  </div>

  <!-- AES -->
  <div id="sp-aes" class="sp">
    <div class="fg">
      <div class="fr inline">
        <label style="margin:0;margin-right:8px">模式</label>
        <select id="a-mode"><option value="cbc">CBC</option><option value="ecb">ECB</option></select>
      </div>
      <div class="fr"><label>密钥 (Hex)</label>
        <input id="a-key" type="text" placeholder="32/48/64 位 hex (AES-128/192/256)"></div>
      <div class="fr"><label>IV (Hex, CBC 可选)</label>
        <input id="a-iv" type="text" placeholder="32 位 hex (16B)，留空自动生成"></div>
      <div class="fr"><label>数据</label>
        <textarea id="a-data" rows="4" placeholder="加密: 明文 / 解密: Base64 密文"></textarea></div>
    </div>
    <div class="acts">
      <button class="btn bp" onclick="doAes('encrypt')">加密</button>
      <button class="btn bp" onclick="doAes('decrypt')">解密</button>
      <button class="btn bc" onclick="cp('a-out')">复制</button>
    </div>
    <div class="fr"><textarea id="a-out" rows="4" readonly placeholder="结果..."></textarea></div>
  </div>

  <!-- DES / 3DES -->
  <div id="sp-des" class="sp">
    <div class="fg">
      <div class="fr inline">
        <label style="margin:0;margin-right:8px">算法</label>
        <select id="de-algo"><option value="des">DES</option><option value="3des">3DES</option></select>
      </div>
      <div class="fr"><label>密钥 (Hex)</label>
        <input id="de-key" type="text" placeholder="DES: 16位hex(8B) / 3DES: 32或48位hex"></div>
      <div class="fr"><label>IV (Hex, 可选)</label>
        <input id="de-iv" type="text" placeholder="16 位 hex (8B)，留空自动生成"></div>
      <div class="fr"><label>数据</label>
        <textarea id="de-data" rows="4" placeholder="加密: 明文 / 解密: Base64 密文"></textarea></div>
    </div>
    <div class="acts">
      <button class="btn bp" onclick="doDes('encrypt')">加密</button>
      <button class="btn bp" onclick="doDes('decrypt')">解密</button>
      <button class="btn bc" onclick="cp('de-out')">复制</button>
    </div>
    <div class="fr"><textarea id="de-out" rows="4" readonly placeholder="结果..."></textarea></div>
  </div>

  <!-- RSA -->
  <div id="sp-rsa" class="sp">
    <div class="fg">
      <div class="acts" style="margin-top:0">
        <label style="margin:0;margin-right:4px">密钥长度</label>
        <select id="r-bits"><option value="2048">2048</option><option value="4096">4096</option></select>
        <button class="btn bp" onclick="doRsa('generate')">生成密钥对</button>
      </div>
      <div class="fr"><label>公钥 (PEM)</label>
        <textarea id="r-pub" rows="4" placeholder="RSA 公钥..."></textarea></div>
      <div class="fr"><label>私钥 (PEM)</label>
        <textarea id="r-priv" rows="4" placeholder="RSA 私钥..."></textarea></div>
      <div class="fr"><label>数据</label>
        <textarea id="r-data" rows="3" placeholder="加密: 明文 / 解密: Base64 密文"></textarea></div>
    </div>
    <div class="acts">
      <button class="btn bp" onclick="doRsa('encrypt')">公钥加密</button>
      <button class="btn bp" onclick="doRsa('decrypt')">私钥解密</button>
      <button class="btn bc" onclick="cp('r-out')">复制</button>
    </div>
    <div class="fr"><textarea id="r-out" rows="3" readonly placeholder="结果..."></textarea></div>
  </div>

  <!-- Ed25519 -->
  <div id="sp-ed" class="sp">
    <div class="fg">
      <div class="acts" style="margin-top:0">
        <button class="btn bp" onclick="doEd('generate')">生成密钥对</button>
      </div>
      <div class="fr"><label>公钥 (PEM)</label>
        <textarea id="e-pub" rows="3" placeholder="Ed25519 公钥..."></textarea></div>
      <div class="fr"><label>私钥 (PEM)</label>
        <textarea id="e-priv" rows="3" placeholder="Ed25519 私钥..."></textarea></div>
      <div class="fr"><label>数据</label>
        <textarea id="e-data" rows="3" placeholder="签名/验证的数据..."></textarea></div>
      <div class="fr"><label>签名 (Base64, 验证时填写)</label>
        <input id="e-sig" type="text" placeholder="Base64 签名"></div>
    </div>
    <div class="acts">
      <button class="btn bp" onclick="doEd('sign')">签名</button>
      <button class="btn bp" onclick="doEd('verify')">验证</button>
      <button class="btn bc" onclick="cp('e-out')">复制</button>
    </div>
    <div class="fr"><textarea id="e-out" rows="2" readonly placeholder="结果..."></textarea></div>
  </div>

  <!-- 证书解析 -->
  <div id="sp-cert" class="sp">
    <div class="fr"><label>证书内容 (PEM / Base64 DER)</label>
      <textarea id="ct-in" rows="10"
        placeholder="粘贴 PEM 证书 (-----BEGIN CERTIFICATE-----) 或 Base64 编码的 DER..."></textarea></div>
    <div class="acts">
      <button class="btn bp" onclick="doCert()">解析</button>
      <button class="btn bc" onclick="cp('ct-out')">复制</button>
    </div>
    <div class="fr">
      <textarea id="ct-out" rows="16" readonly placeholder="证书信息..."></textarea></div>
  </div>
</div>

<!-- ===== URL 编解码 ===== -->
<div id="p-url" class="panel">
  <h2>URL 编解码</h2>
  <div class="fr"><label>输入</label><textarea id="u-in" rows="8" placeholder="输入文本..."></textarea></div>
  <div class="acts">
    <button class="btn bp" onclick="doUrl('encode')">编码</button>
    <button class="btn bp" onclick="doUrl('decode')">解码</button>
    <button class="btn bc" onclick="cp('u-out')">复制</button>
  </div>
  <div class="fr"><label>结果</label><textarea id="u-out" rows="8" readonly placeholder="输出..."></textarea></div>
</div>

<!-- ===== Base64 编解码 ===== -->
<div id="p-b64" class="panel">
  <h2>Base64 编解码</h2>
  <div class="fr"><label>输入</label><textarea id="b-in" rows="8" placeholder="输入文本..."></textarea></div>
  <div class="acts">
    <button class="btn bp" onclick="doB64('encode')">编码</button>
    <button class="btn bp" onclick="doB64('decode')">解码</button>
    <button class="btn bc" onclick="cp('b-out')">复制</button>
  </div>
  <div class="fr"><label>结果</label><textarea id="b-out" rows="8" readonly placeholder="输出..."></textarea></div>
</div>

</div>
<script>
const Q=s=>document.getElementById(s);

/* --- 主 Tab 切换 --- */
document.querySelectorAll('.tab').forEach(b=>{
  b.addEventListener('click',()=>{
    document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
    b.classList.add('active');
    Q('p-'+b.dataset.tab).classList.add('active');
  });
});

/* --- 子 Tab 切换 --- */
document.querySelectorAll('.stab').forEach(b=>{
  b.addEventListener('click',()=>{
    const box=b.closest('.panel');
    box.querySelectorAll('.stab').forEach(t=>t.classList.remove('active'));
    box.querySelectorAll('.sp').forEach(p=>p.classList.remove('active'));
    b.classList.add('active');
    Q('sp-'+b.dataset.st).classList.add('active');
  });
});

/* --- API 调用 --- */
async function api(path,body){
  const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const d=await r.json();
  if(d.error) throw new Error(d.error);
  return d.result;
}
function sR(id,v){const e=Q(id);e.value=v;e.style.color='';}
function sE(id,v){const e=Q(id);e.value='错误: '+v;e.style.color='#dc2626';}
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function cp(id){
  const e=Q(id), t=e.value||e.textContent;
  navigator.clipboard.writeText(t).then(()=>{
    const b=e.closest('.fr,.acts')?.querySelector('.bc');
    if(b){const o=b.textContent;b.textContent='已复制 ✓';setTimeout(()=>b.textContent=o,1200);}
  });
}

/* --- 文本对比 --- */
async function doDiff(){
  try{
    const r=await api('/api/diff',{text1:Q('d-t1').value,text2:Q('d-t2').value});
    Q('diff-result').innerHTML=r.split('\n').map(l=>{
      if(l.startsWith('---')||l.startsWith('+++')) return '<span class="dh">'+esc(l)+'</span>';
      if(l.startsWith('@@')) return '<span class="dr">'+esc(l)+'</span>';
      if(l.startsWith('+')) return '<span class="da">'+esc(l)+'</span>';
      if(l.startsWith('-')) return '<span class="dd">'+esc(l)+'</span>';
      return esc(l);
    }).join('\n');
  }catch(e){Q('diff-result').innerHTML='<span class="err">'+esc(e.message)+'</span>';}
}

/* --- JSON --- */
async function doJson(a){
  try{sR('j-out',await api('/api/json',{text:Q('j-in').value,action:a}));}
  catch(e){sE('j-out',e.message);}
}

/* --- 时间戳 --- */
async function doTs(a){
  try{
    const r=await api('/api/timestamp',{value:Q('ts-in').value,action:a});
    const box=Q('ts-result');box.style.display='block';
    box.innerHTML=Object.entries(r).map(([k,v])=>'<div><strong>'+k+':</strong> <code>'+v+'</code></div>').join('');
  }catch(e){const box=Q('ts-result');box.style.display='block';
    box.innerHTML='<div class="err">'+esc(e.message)+'</div>';}
}
setInterval(()=>{
  const n=Math.floor(Date.now()/1000);
  Q('ts-now').textContent=n;
  Q('ts-dt').textContent=new Date().toLocaleString('zh-CN');
},1000);

/* --- 哈希 --- */
async function doHash(a){
  try{sR('h-out',await api('/api/hash',{text:Q('h-in').value,algorithm:a}));}
  catch(e){sE('h-out',e.message);}
}

/* --- HMAC --- */
async function doHmac(a){
  try{sR('hm-out',await api('/api/hmac',{text:Q('hm-in').value,key:Q('hm-key').value,algorithm:a}));}
  catch(e){sE('hm-out',e.message);}
}

/* --- AES --- */
async function doAes(act){
  try{const b={data:Q('a-data').value,key:Q('a-key').value,
    iv:Q('a-iv').value,mode:Q('a-mode').value,action:act};
    sR('a-out',await api('/api/aes',b));
  }catch(e){sE('a-out',e.message);}
}

/* --- DES/3DES --- */
async function doDes(act){
  try{
    const algo=Q('de-algo').value;
    sR('de-out',await api('/api/'+algo,{data:Q('de-data').value,key:Q('de-key').value,iv:Q('de-iv').value,action:act}));
  }catch(e){sE('de-out',e.message);}
}

/* --- RSA --- */
async function doRsa(act){
  try{
    const body={action:act};
    if(act==='generate') body.key_size=parseInt(Q('r-bits').value);
    else if(act==='encrypt'){body.public_key=Q('r-pub').value;body.data=Q('r-data').value;}
    else{body.private_key=Q('r-priv').value;body.data=Q('r-data').value;}
    const r=await api('/api/rsa',body);
    if(act==='generate'){Q('r-pub').value=r.public_key;Q('r-priv').value=r.private_key;sR('r-out','密钥对已生成 ✓');}
    else sR('r-out',r.result);
  }catch(e){sE('r-out',e.message);}
}

/* --- Ed25519 --- */
async function doEd(act){
  try{
    const body={action:act};
    if(act==='generate'){}
    else if(act==='sign'){body.private_key=Q('e-priv').value;body.data=Q('e-data').value;}
    else{body.public_key=Q('e-pub').value;body.data=Q('e-data').value;body.signature=Q('e-sig').value;}
    const r=await api('/api/ed25519',body);
    if(act==='generate'){Q('e-pub').value=r.public_key;Q('e-priv').value=r.private_key;sR('e-out','密钥对已生成 ✓');}
    else if(act==='sign'){Q('e-sig').value=r.signature;sR('e-out','签名成功 ✓');}
    else sR('e-out',r.message);
  }catch(e){sE('e-out',e.message);}
}

/* --- 证书解析 --- */
async function doCert(){
  try{sR('ct-out',await api('/api/cert',{pem:Q('ct-in').value}));}
  catch(e){sE('ct-out',e.message);}
}

/* --- URL --- */
async function doUrl(a){
  try{sR('u-out',await api('/api/url',{text:Q('u-in').value,action:a}));}
  catch(e){sE('u-out',e.message);}
}

/* --- Base64 --- */
async function doB64(a){
  try{sR('b-out',await api('/api/base64',{text:Q('b-in').value,action:a}));}
  catch(e){sE('b-out',e.message);}
}
</script>
</body>
</html>"""


# ============================================================
# 工具函数（标准库）
# ============================================================


def _text_diff(text1: str, text2: str) -> str:
    """生成两段文本的统一差异比较"""
    lines1 = text1.splitlines(keepends=True)
    lines2 = text2.splitlines(keepends=True)
    diff = list(difflib.unified_diff(lines1, lines2, fromfile="文本 A", tofile="文本 B"))
    if not diff:
        return "两段文本完全相同 ✓"
    return "".join(diff)


def _json_format(text: str, action: str) -> str:
    """JSON 格式化 / 压缩 / 校验 / 转义 / 去转义"""
    if action == "escape":
        json.loads(text)
        return json.dumps(text, ensure_ascii=False)
    elif action == "unescape":
        unescaped = json.loads(text)
        if not isinstance(unescaped, str):
            return text
        return unescaped
    parsed = json.loads(text)
    if action == "format":
        return json.dumps(parsed, indent=2, ensure_ascii=False)
    elif action == "minify":
        return json.dumps(parsed, separators=(",", ":"), ensure_ascii=False)
    elif action == "validate":
        return "JSON 格式正确 ✓"
    raise ValueError(f"未知操作: {action}")


def _timestamp_convert(value: str, action: str) -> dict:
    """时间戳与日期时间互转"""
    if action == "now":
        now = datetime.now()
        utc_now = datetime.now(tz=timezone.utc)
        ts = now.timestamp()
        return {
            "秒级时间戳": int(ts),
            "毫秒级时间戳": int(ts * 1000),
            "本地时间": now.strftime("%Y-%m-%d %H:%M:%S"),
            "UTC 时间": utc_now.strftime("%Y-%m-%d %H:%M:%S"),
            "ISO 8601": utc_now.isoformat(),
        }
    if action == "to_datetime":
        ts = float(value)
        if ts > 1e12:
            ts = ts / 1000
        dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
        dt_local = datetime.fromtimestamp(ts)
        return {
            "秒级时间戳": int(ts),
            "毫秒级时间戳": int(ts * 1000),
            "本地时间": dt_local.strftime("%Y-%m-%d %H:%M:%S"),
            "UTC 时间": dt_utc.strftime("%Y-%m-%d %H:%M:%S"),
            "ISO 8601": dt_utc.isoformat(),
        }
    if action == "to_timestamp":
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(value, fmt)
                ts = dt.timestamp()
                return {
                    "秒级时间戳": int(ts),
                    "毫秒级时间戳": int(ts * 1000),
                    "本地时间": dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "ISO 8601": dt.isoformat(),
                }
            except ValueError:
                continue
        raise ValueError(f"无法解析日期格式: {value}，支持格式: YYYY-MM-DD HH:MM:SS / YYYY-MM-DD 等")
    raise ValueError(f"未知操作: {action}")


def _hash_text(text: str, algorithm: str) -> str:
    """计算文本哈希值"""
    algo_map = {"md5": hashlib.md5, "sha1": hashlib.sha1, "sha256": hashlib.sha256, "sha512": hashlib.sha512}
    if algorithm not in algo_map:
        raise ValueError(f"不支持的哈希算法: {algorithm}")
    return algo_map[algorithm](text.encode("utf-8")).hexdigest()


def _hmac_text(text: str, key: str, algorithm: str) -> str:
    """计算 HMAC"""
    algo_map = {"hmac-sha256": "sha256", "hmac-sha512": "sha512"}
    if algorithm not in algo_map:
        raise ValueError(f"不支持的 HMAC 算法: {algorithm}")
    if not key:
        raise ValueError("HMAC 密钥不能为空")
    return hmac_mod.new(key.encode("utf-8"), text.encode("utf-8"), algo_map[algorithm]).hexdigest()


def _url_process(text: str, action: str) -> str:
    """URL 编解码"""
    if action == "encode":
        return urllib.parse.quote(text, safe="")
    elif action == "decode":
        return urllib.parse.unquote(text)
    raise ValueError(f"未知操作: {action}")


def _base64_process(text: str, action: str) -> str:
    """Base64 编解码"""
    if action == "encode":
        return b64_mod.b64encode(text.encode("utf-8")).decode("ascii")
    elif action == "decode":
        return b64_mod.b64decode(text).decode("utf-8")
    raise ValueError(f"未知操作: {action}")


# ============================================================
# 加解密函数（需要 cryptography 库）
# ============================================================

_CRYPTO_HINT = "此功能需要安装 cryptography 库: pip install cryptography"


def _aes_process(data: str, key_hex: str, iv_hex: str, mode: str, action: str) -> str:
    """AES 加解密（CBC / ECB，PKCS7 填充）"""
    try:
        from cryptography.hazmat.primitives import padding as sym_padding
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
        from cryptography.hazmat.primitives.ciphers import modes as cm
    except ImportError:
        raise RuntimeError(_CRYPTO_HINT) from None

    key = bytes.fromhex(key_hex)
    if len(key) not in (16, 24, 32):
        raise ValueError(f"AES 密钥长度须为 16/24/32 字节，当前 {len(key)} 字节")

    if action == "encrypt":
        padder = sym_padding.PKCS7(128).padder()
        padded = padder.update(data.encode("utf-8")) + padder.finalize()
        if mode == "cbc":
            iv = bytes.fromhex(iv_hex) if iv_hex else os.urandom(16)
            if len(iv) != 16:
                raise ValueError(f"AES-CBC IV 须为 16 字节，当前 {len(iv)} 字节")
            enc = Cipher(algorithms.AES(key), cm.CBC(iv)).encryptor()
            ct = enc.update(padded) + enc.finalize()
            return b64_mod.b64encode(iv + ct).decode("ascii")
        else:
            enc = Cipher(algorithms.AES(key), cm.ECB()).encryptor()
            ct = enc.update(padded) + enc.finalize()
            return b64_mod.b64encode(ct).decode("ascii")
    elif action == "decrypt":
        raw = b64_mod.b64decode(data)
        if mode == "cbc":
            iv, ct = raw[:16], raw[16:]
            dec = Cipher(algorithms.AES(key), cm.CBC(iv)).decryptor()
        else:
            ct = raw
            dec = Cipher(algorithms.AES(key), cm.ECB()).decryptor()
        padded = dec.update(ct) + dec.finalize()
        unpadder = sym_padding.PKCS7(128).unpadder()
        return (unpadder.update(padded) + unpadder.finalize()).decode("utf-8")
    raise ValueError(f"未知操作: {action}")


def _des_process(data: str, key_hex: str, iv_hex: str, action: str, *, triple: bool = False) -> str:
    """DES / 3DES 加解密（CBC，PKCS7 填充）"""
    try:
        from cryptography.hazmat.primitives import padding as sym_padding
        from cryptography.hazmat.primitives.ciphers import Cipher
        from cryptography.hazmat.primitives.ciphers import modes as cm

        try:
            from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
        except ImportError:
            from cryptography.hazmat.primitives.ciphers.algorithms import TripleDES
    except ImportError:
        raise RuntimeError(_CRYPTO_HINT) from None

    key = bytes.fromhex(key_hex)
    if triple:
        if len(key) not in (16, 24):
            raise ValueError(f"3DES 密钥须为 16/24 字节，当前 {len(key)} 字节")
    else:
        if len(key) != 8:
            raise ValueError(f"DES 密钥须为 8 字节，当前 {len(key)} 字节")
        key = key * 3  # TripleDES(K,K,K) == DES(K)

    if action == "encrypt":
        iv = bytes.fromhex(iv_hex) if iv_hex else os.urandom(8)
        if len(iv) != 8:
            raise ValueError(f"DES IV 须为 8 字节，当前 {len(iv)} 字节")
        padder = sym_padding.PKCS7(64).padder()
        padded = padder.update(data.encode("utf-8")) + padder.finalize()
        enc = Cipher(TripleDES(key), cm.CBC(iv)).encryptor()
        ct = enc.update(padded) + enc.finalize()
        return b64_mod.b64encode(iv + ct).decode("ascii")
    elif action == "decrypt":
        raw = b64_mod.b64decode(data)
        iv, ct = raw[:8], raw[8:]
        dec = Cipher(TripleDES(key), cm.CBC(iv)).decryptor()
        padded = dec.update(ct) + dec.finalize()
        unpadder = sym_padding.PKCS7(64).unpadder()
        return (unpadder.update(padded) + unpadder.finalize()).decode("utf-8")
    raise ValueError(f"未知操作: {action}")


def _rsa_process(action: str, **kwargs: str | int) -> dict:
    """RSA 密钥生成 / 加密 / 解密（OAEP + SHA256）"""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding as ap
        from cryptography.hazmat.primitives.asymmetric import rsa
    except ImportError:
        raise RuntimeError(_CRYPTO_HINT) from None

    oaep = ap.OAEP(mgf=ap.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)

    if action == "generate":
        key_size = int(kwargs.get("key_size", 2048))
        priv = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
        return {
            "private_key": priv.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            ).decode("ascii"),
            "public_key": priv.public_key()
            .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
            .decode("ascii"),
        }
    elif action == "encrypt":
        pub = serialization.load_pem_public_key(str(kwargs["public_key"]).encode("utf-8"))
        ct = pub.encrypt(str(kwargs["data"]).encode("utf-8"), oaep)
        return {"result": b64_mod.b64encode(ct).decode("ascii")}
    elif action == "decrypt":
        priv = serialization.load_pem_private_key(str(kwargs["private_key"]).encode("utf-8"), password=None)
        pt = priv.decrypt(b64_mod.b64decode(str(kwargs["data"])), oaep)
        return {"result": pt.decode("utf-8")}
    raise ValueError(f"未知操作: {action}")


def _ed25519_process(action: str, **kwargs: str) -> dict:
    """Ed25519 密钥生成 / 签名 / 验证"""
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        raise RuntimeError(_CRYPTO_HINT) from None

    if action == "generate":
        priv = Ed25519PrivateKey.generate()
        return {
            "private_key": priv.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            ).decode("ascii"),
            "public_key": priv.public_key()
            .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
            .decode("ascii"),
        }
    elif action == "sign":
        priv = serialization.load_pem_private_key(str(kwargs["private_key"]).encode("utf-8"), password=None)
        sig = priv.sign(str(kwargs["data"]).encode("utf-8"))
        return {"signature": b64_mod.b64encode(sig).decode("ascii")}
    elif action == "verify":
        pub = serialization.load_pem_public_key(str(kwargs["public_key"]).encode("utf-8"))
        try:
            pub.verify(b64_mod.b64decode(str(kwargs["signature"])), str(kwargs["data"]).encode("utf-8"))
            return {"valid": True, "message": "签名验证通过 ✓"}
        except Exception:
            return {"valid": False, "message": "签名验证失败 ✗"}
    raise ValueError(f"未知操作: {action}")


def _cert_parse(pem_text: str) -> str:
    """解析 X.509 证书，提取主要字段"""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
    except ImportError:
        raise RuntimeError(_CRYPTO_HINT) from None

    pem_text = pem_text.strip()
    if pem_text.startswith("-----BEGIN"):
        cert = x509.load_pem_x509_certificate(pem_text.encode("utf-8"))
    else:
        cert = x509.load_der_x509_certificate(b64_mod.b64decode(pem_text))

    def _dn(name: x509.Name) -> str:
        parts = []
        for attr in name:
            parts.append(f"{attr.oid._name}={attr.value}")
        return ", ".join(parts)

    def _hex(data: bytes) -> str:
        return ":".join(f"{b:02X}" for b in data)

    lines = [
        f"版本:          V{cert.version.value + 1}",
        f"序列号:        {cert.serial_number}",
        f"签名算法:      {cert.signature_algorithm_oid._name}",
        f"颁发者:        {_dn(cert.issuer)}",
        f"使用者:        {_dn(cert.subject)}",
        f"有效期从:      {cert.not_valid_before_utc}",
        f"有效期至:      {cert.not_valid_after_utc}",
        f"公钥算法:      {cert.public_key().__class__.__name__}",
    ]

    try:
        fp = cert.fingerprint(hashes.SHA256())
        lines.append(f"SHA256 指纹:   {_hex(fp)}")
    except Exception:
        pass

    try:
        fp1 = cert.fingerprint(hashes.SHA1())
        lines.append(f"SHA1 指纹:     {_hex(fp1)}")
    except Exception:
        pass

    for ext in cert.extensions:
        try:
            if isinstance(ext.value, x509.SubjectAlternativeName):
                sans = [str(n.value) for n in ext.value]
                lines.append(f"SAN:           {', '.join(sans)}")
            elif isinstance(ext.value, x509.BasicConstraints):
                ca = "是" if ext.value.ca else "否"
                lines.append(f"CA:            {ca}")
            elif isinstance(ext.value, x509.KeyUsage):
                usages = []
                for field in (
                    "digital_signature",
                    "key_encipherment",
                    "content_commitment",
                    "data_encipherment",
                    "key_agreement",
                    "key_cert_sign",
                    "crl_sign",
                ):
                    if getattr(ext.value, field, False):
                        usages.append(field)
                if usages:
                    lines.append(f"密钥用途:      {', '.join(usages)}")
        except Exception:
            continue

    return "\n".join(lines)


# ============================================================
# HTTP 服务
# ============================================================


def _build_routes() -> dict:
    """构建 API 路由映射"""
    return {
        "/api/diff": lambda d: {"result": _text_diff(d.get("text1", ""), d.get("text2", ""))},
        "/api/json": lambda d: {"result": _json_format(d.get("text", ""), d.get("action", "format"))},
        "/api/timestamp": lambda d: {"result": _timestamp_convert(d.get("value", ""), d.get("action", "now"))},
        "/api/hash": lambda d: {"result": _hash_text(d.get("text", ""), d.get("algorithm", "md5"))},
        "/api/hmac": lambda d: {
            "result": _hmac_text(d.get("text", ""), d.get("key", ""), d.get("algorithm", "hmac-sha256"))
        },
        "/api/aes": lambda d: {
            "result": _aes_process(
                d.get("data", ""), d.get("key", ""), d.get("iv", ""), d.get("mode", "cbc"), d.get("action", "encrypt")
            )
        },
        "/api/des": lambda d: {
            "result": _des_process(
                d.get("data", ""), d.get("key", ""), d.get("iv", ""), d.get("action", "encrypt"), triple=False
            )
        },
        "/api/3des": lambda d: {
            "result": _des_process(
                d.get("data", ""), d.get("key", ""), d.get("iv", ""), d.get("action", "encrypt"), triple=True
            )
        },
        "/api/rsa": lambda d: {"result": _rsa_process(d.get("action", "generate"), **d)},
        "/api/ed25519": lambda d: {"result": _ed25519_process(d.get("action", "generate"), **d)},
        "/api/cert": lambda d: {"result": _cert_parse(d.get("pem", ""))},
        "/api/url": lambda d: {"result": _url_process(d.get("text", ""), d.get("action", "encode"))},
        "/api/base64": lambda d: {"result": _base64_process(d.get("text", ""), d.get("action", "encode"))},
    }


class _WebtoolHandler(BaseHTTPRequestHandler):
    """Web 工具 HTTP 请求处理器"""

    _routes: dict = {}
    _page_html: str = ""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        logger.debug(format, *args)

    def do_GET(self) -> None:
        """GET 请求 → 返回工具页面"""
        path = self.path.split("?")[0]
        if path in ("/", ""):
            self._respond_html(self._page_html)
        elif path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        """POST 请求 → API 调用"""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._respond_json({"error": "无效的 JSON 请求体"}, 400)
            return

        path = self.path.split("?")[0]
        handler = self._routes.get(path)
        if not handler:
            self._respond_json({"error": f"未知的 API: {path}"}, 404)
            return

        try:
            result = handler(data)
            self._respond_json(result)
        except Exception as e:
            logger.debug("API 错误 [%s]: %s", path, e)
            self._respond_json({"error": str(e)}, 400)

    def _respond_html(self, html: str) -> None:
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _respond_json(self, obj: dict, status: int = 200) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@dataclass
class WebtoolServerConfig:
    host: str = "127.0.0.1"
    port: int = 9000


def start_server(config: WebtoolServerConfig) -> None:
    """启动 Webtool HTTP 服务（阻塞）"""
    _WebtoolHandler._routes = _build_routes()
    _WebtoolHandler._page_html = _HTML_PAGE.replace("__VERSION__", __version__)

    server = HTTPServer((config.host, config.port), _WebtoolHandler)
    server.serve_forever()
