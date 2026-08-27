import projects from './projects'
import datasets from './datasets'
import annotations from './annotations'
import preprocess from './preprocess'
import files from './files'
import models from './models'
import train from './train'
import cluster from './cluster'
import sam from './sam'
import fs from './fs'
import scenes from './scenes'
import xal from './xal'
import dashboard from './dashboard'

/** 统一 API 入口：新增领域模块时在此挂载，页面 import { api } from '../api' 不变。 */
export const api = {
  projects,
  datasets,
  annotations,
  ops: preprocess.ops,
  preview: preprocess.preview,
  pipelines: preprocess.pipelines,
  files,
  models,
  train,
  cluster,
  sam,
  fs,
  scenes,
  xal,
  dashboard,
}

export default api
