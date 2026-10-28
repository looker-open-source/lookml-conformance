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

// Black-box oracle: node-lookml-parser (Fabio Beltramini). Prints per-model resolved views.
const fs = require('fs'), path = require('path');
const lp = require(path.join(process.env.HOME, 'work/oracle/node_modules/lookml-parser'));
const root = path.resolve(process.argv[2]);
function walk(d){return fs.readdirSync(d,{withFileTypes:true}).flatMap(e=>e.isDirectory()?walk(path.join(d,e.name)):[path.join(d,e.name)])}
(async()=>{
  const files = walk(root).filter(f=>/\.(lkml|lookml)$/.test(f)).map(f=>({path:path.relative(root,f),content:fs.readFileSync(f,'utf8')}));
  const project = await lp.parseFiles({source:files, input:files, modelAssembly:true, strings:false, console:{log(){},warn(){},error(){}}}).catch(e=>({error:String(e)}));
  if(project.error){console.log(JSON.stringify({error:project.error}));return}
  const out={}, errs=project.errors||[];
  for(const [m,model] of Object.entries(project.model||{})){
    out[m]={};
    for(const [v,view] of Object.entries(model.view||{})){
      const dims={};
      for(const t of ['dimension','measure','dimension_group']) for(const [n,f] of Object.entries(view[t]||{})) dims[n]={sql:f.sql??null,label:f.label??null,type:f.type??null};
      out[m][v]={sql_table_name:view.sql_table_name??null, derived_sql:view.derived_table?.sql??null, description:view.description??null, fields:dims};
    }
  }
  console.log(JSON.stringify({models:out, errors:errs.map(e=>e.message||String(e)).slice(0,10)},null,1));
})();
