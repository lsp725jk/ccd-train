<script setup>
import { NInputNumber, NSelect, NSlider, NSwitch } from 'naive-ui'

defineProps({ params: { type: Array, default: () => [] } })
const model = defineModel({ type: Object, default: () => ({}) })
</script>

<template>
  <div style="padding: 4px 0">
    <div v-for="p in params" :key="p.name" style="margin-bottom: 14px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
        <label style="font-size:0.85rem;color:var(--text-color)">{{ p.label }}</label>
        <span v-if="p.type !== 'bool'" style="font-size:0.8rem;color:var(--el-color-primary);font-variant-numeric:tabular-nums">
          {{ model[p.name] }}
        </span>
      </div>
      <div v-if="p.type === 'int' || p.type === 'float'" style="display:flex;align-items:center;gap:8px">
        <n-slider v-model:value="model[p.name]" :min="p.min" :max="p.max" :step="p.step" style="flex:1" />
        <n-input-number v-model:value="model[p.name]" :min="p.min" :max="p.max" :step="p.step"
                        size="small" style="width:86px" :placeholder="''" />
      </div>
      <n-switch v-else-if="p.type === 'bool'" v-model:value="model[p.name]" />
      <n-select v-else-if="p.type === 'select'" v-model:value="model[p.name]" size="small"
                :options="(p.options || []).map(o => ({ label: o, value: o }))" />
    </div>
    <div v-if="!params.length" style="color:var(--text-muted);font-size:0.82rem;padding:8px 0">
      该算子无参数
    </div>
  </div>
</template>
