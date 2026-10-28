// Copyright 2026 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     https://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

// Black-box oracle (node-lookml-parser): per model, resolved views + views referenced by explores.
const fs = require('fs'), path = require('path');
const lp = require(path.join(process.env.HOME, 'work/oracle/node_modules/lookml-parser'));
const root = path.resolve(process.argv[2]);
function walk(d){return fs.readdirSync(d,{withFileTypes:true}).flatMap(e=>e.name==='.git'?[]:e.isDirectory()?walk(path.join(d,e.name)):[path.join(d,e.name)])}
const norm=s=>s==null?null:String(s).replace(/\s+/g,' ').trim();
(async()=>{
  const files = walk(root).filter(f=>/\.lkml$/.test(f)&&!/\.dashboard\.lkml$/.test(f)).map(f=>({path:path.relative(root,f),content:fs.readFileSync(f,'utf8')}));
  const project = await lp.parseFiles({source:files, modelAssembly:true, strings:false, console:{log(){},warn(){},error(){}}});
  const out={};
  for(const [m,model] of Object.entries(project.model||{})){
    const views={}, refs=new Set(), explores=[];
    for(const [v,view] of Object.entries(model.view||{})){
      const fields=[];
      for(const t of ['dimension','dimension_group','measure']) for(const n of Object.keys(view[t]||{})) fields.push(n);
      views[v]={sql_table_name:norm(view.sql_table_name), derived_sql:norm(view.derived_table?.sql), fields:fields.sort()};
    }
    for(const [e,ex] of Object.entries(model.explore||{})){
      if(e.startsWith('+')||ex.extension==='required') continue;
      refs.add(ex.from||ex.view_name||e);
      for(const [j,jn] of Object.entries(ex.join||{})) refs.add(jn.from||j);
      explores.push({name:e, view_name:ex.from||ex.view_name||e, joins:Object.entries(ex.join||{}).map(([j,jn])=>({name:j, from:jn.from||null}))});
    }
    out[m]={views, explore_views:[...refs].sort(), explores};
  }
  console.log(JSON.stringify(out));
})().catch(e=>{console.log(JSON.stringify({error:String(e.stack||e)}))});
