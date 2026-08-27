<script setup>
defineProps({ params: { type: Array, default: () => [] } })
const model = defineModel({ type: Object, default: () => ({}) })
</script>

<template>
  <div style="padding: 4px 0">
    <div v-for="p in params" :key="p.name" style="margin-bottom: 14px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
        <label style="font-size:0.85rem;color:#4a433c">{{ p.label }}</label>
        <span v-if="p.type !== 'bool'" style="font-size:0.8rem;color:#4a6b4a;font-variant-numeric:tabular-nums">
          {{ model[p.name] }}
        </span>
      </div>
      <el-slider v-if="p.type === 'int' || p.type === 'float'" v-model="model[p.name]"
                 :min="p.min" :max="p.max" :step="p.step" size="small" />
      <el-switch v-else-if="p.type === 'bool'" v-model="model[p.name]" />
      <el-select v-else-if="p.type === 'select'" v-model="model[p.name]" size="small" style="width:100%">
        <el-option v-for="o in p.options" :key="o" :label="o" :value="o" />
      </el-select>
    </div>
    <div v-if="!params.length" style="color:#8a8175;font-size:0.82rem;padding:8px 0">
      该算子无参数
    </div>
  </div>
</template>
