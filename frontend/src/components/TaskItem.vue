<script setup>
import { NButton, NProgress } from 'naive-ui'

defineProps({
  task: { type: Object, required: true },
  active: { type: Boolean, default: false },
})
defineEmits(['select', 'stop', 'resubmit'])

const statusMeta = {
  queued: { text: '排队中', color: '#8a8175' },
  running: { text: '训练中', color: '#4a6b4a' },
  success: { text: '成功', color: '#4a6b4a' },
  failed: { text: '失败', color: '#8b2c1f' },
  stopped: { text: '已停止', color: '#8a8175' },
}
</script>

<template>
  <div class="task-item" :class="{ on: active }" @click="$emit('select', task)">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <span style="font-weight:500">{{ task.model_name }}</span>
      <span :style="{ color: statusMeta[task.status]?.color }">{{ statusMeta[task.status]?.text || task.status }}</span>
    </div>
    <div style="font-size:0.78rem;color:#8a8175;margin:2px 0 6px">
      #{{ task.id }} · {{ task.engine }} · {{ task.created_at }}
    </div>
    <n-progress type="line" :percentage="Math.round(task.progress * 100)" :stroke-width="6"
                :status="task.status === 'failed' ? 'error' : 'default'" />
    <div style="display:flex;gap:6px;margin-top:6px">
      <n-button v-if="['queued', 'running'].includes(task.status)" size="small" type="error" secondary
                 @click.stop="$emit('stop', task)">停止</n-button>
      <n-button v-if="['failed', 'stopped', 'success'].includes(task.status)" size="small" secondary
                 @click.stop="$emit('resubmit', task)">重新提交</n-button>
    </div>
  </div>
</template>

<style scoped>
.task-item {
  padding: 10px 12px;
  border: 1px solid #d8cfbe;
  border-radius: 6px;
  margin-bottom: 8px;
  cursor: pointer;
  background: #fbf8f1;
}
.task-item.on { border-color: #4a6b4a; background: #eef3ee; }
</style>
