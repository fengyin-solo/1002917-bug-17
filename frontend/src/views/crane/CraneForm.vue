<template>
  <div v-if="open" class="modal-mask" @click.self="emit('close')">
    <div class="modal">
      <header class="modal-head">
        <h3>{{ isEdit ? '修改起重机台账' : '登记起重机' }}</h3>
        <button class="link" type="button" @click="emit('close')">关闭</button>
      </header>
      <form class="modal-body" @submit.prevent="submit">
        <label v-for="field in fields" :key="field.key" class="form-item">
          <span>{{ field.label }}<em v-if="field.required">*</em></span>
          <input v-model="form[field.key]" :placeholder="`请输入${field.label}`" />
        </label>
        <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>
        <footer class="modal-foot">
          <button class="btn ghost" type="button" @click="emit('close')">取消</button>
          <button class="btn primary" type="submit">{{ isEdit ? '保存修改' : '确认登记' }}</button>
        </footer>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'

import { request } from '@/api/client'

export interface CraneFormValues {
  额定起重量?: string
  上次年检?: string
  工作级别?: string
  跨度?: string
  操作人员?: string
  起重机编号?: string
  起重机类型?: string
  id?: number
}

const props = defineProps<{ open: boolean; entry?: CraneFormValues | null }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'saved', message: string): void
}>()

// 与后端 EDITABLE_FIELDS 对齐；前三项为登记必填。
const fields = [
  { key: '起重机编号', label: '起重机编号', required: true },
  { key: '起重机类型', label: '起重机类型', required: true },
  { key: '额定起重量', label: '额定起重量', required: true },
  { key: '跨度', label: '跨度', required: false },
  { key: '工作级别', label: '工作级别', required: false },
  { key: '操作人员', label: '操作人员', required: false },
  { key: '上次年检', label: '上次年检（YYYY-MM-DD）', required: false },
] as const

type FormState = Record<string, string>

const emptyForm = (): FormState => Object.fromEntries(fields.map((field) => [field.key, '']))
const form = reactive<FormState>(emptyForm())
const errorMessage = ref('')

const isEdit = computed(() => Number(props.entry?.id ?? 0) > 0)

watch(
  () => props.open,
  (open) => {
    if (!open) return
    errorMessage.value = ''
    const base = emptyForm()
    if (props.entry) {
      for (const field of fields) {
        const value = props.entry[field.key as keyof CraneFormValues]
        if (value !== undefined && value !== null) base[field.key] = String(value)
      }
    }
    Object.assign(form, base)
  },
)

async function submit() {
  errorMessage.value = ''
  const id = Number(props.entry?.id ?? 0)
  const url = id ? `/api/crane/${id}` : '/api/crane'
  try {
    const response = await request(url, {
      method: id ? 'PATCH' : 'POST',
      body: JSON.stringify({ values: { ...form } }),
    })
    const payload = (await response.json()) as { ok?: boolean; message?: string }
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message || '保存未生效，请稍后重试')
    }
    emit('saved', payload.message || (id ? '起重机台账已更新' : '起重机已登记'))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '起重机保存失败'
  }
}
</script>
