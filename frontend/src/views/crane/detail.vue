<template>
  <section class="page" data-module="crane-detail">
    <header class="page-head">
      <div>
        <h2>起重机详情</h2>
        <p class="page-desc">
          <RouterLink class="link" to="/crane">← 返回起重机械列表</RouterLink>
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="openEdit">修改台账</button>
      </div>
    </header>

    <div v-if="missingTip" class="warn-banner">
      <strong>资料不全：</strong>{{ missingTip }}
    </div>

    <article v-if="entry" class="detail-card">
      <header class="detail-head">
        <div>
          <h3>{{ entry.起重机编号 }} · {{ entry.起重机类型 }}</h3>
          <span :class="['status-tag', statusClass(entry.status)]">{{ entry.status ?? '—' }}</span>
        </div>
        <p class="page-desc">
          状态须沿 正常 → 超载运行 → 检验中 → 已停用 顺序推进；
          已停用设备须补齐上次年检后方可恢复使用，且停用期间不能再安排检验。
        </p>
      </header>

      <dl class="detail-grid">
        <div v-for="field in detailFields" :key="field.key" class="detail-item">
          <dt>{{ field.label }}</dt>
          <dd v-if="entry[field.key] !== '' && entry[field.key] !== null && entry[field.key] !== undefined">
            {{ entry[field.key] }}
          </dd>
          <dd v-else class="warn-text">未填写{{ field.label }}</dd>
        </div>
      </dl>

      <section class="detail-actions">
        <h4>可执行动作</h4>
        <p v-if="!allowedActions.length" class="page-desc">当前状态下没有可推进的动作。</p>
        <button
          v-for="action in allowedActions"
          :key="action"
          class="btn"
          type="button"
          @click="runAction(action)"
        >
          {{ action }}
        </button>
        <form v-if="entry.status === '已停用' && missingFields.length" class="annual-fill" @submit.prevent="fillAnnual">
          <label>
            <span>补录{{ missingFields.join('、') }}日期</span>
            <input v-model="annualDate" placeholder="YYYY-MM-DD" />
          </label>
          <button class="btn primary" type="submit" :disabled="!annualDate.trim()">补录并恢复使用</button>
        </form>
      </section>

      <footer class="page-foot">
        <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
        <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      </footer>
    </article>

    <CraneForm :open="formOpen" :entry="formEntry" @close="formOpen = false" @saved="onSaved" />
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { request } from '@/api/client'
import CraneForm, { type CraneFormValues } from './CraneForm.vue'

type DetailRow = CraneFormValues & {
  status?: string
  missing_fields?: string[]
  missing_tip?: string
  [key: string]: string | number | string[] | null | undefined
}

const EDITABLE_KEYS = [
  'id', '起重机编号', '起重机类型', '额定起重量', '跨度', '工作级别', '操作人员', '上次年检',
] as const

const route = useRoute()
const router = useRouter()
const ENDPOINT = '/api/crane'

const entry = ref<DetailRow | null>(null)
const errorMessage = ref('')
const noticeMessage = ref('')
const annualDate = ref('')
const formOpen = ref(false)

const detailFields = [
  { key: '起重机编号', label: '起重机编号' },
  { key: '起重机类型', label: '起重机类型' },
  { key: '额定起重量', label: '额定起重量' },
  { key: '跨度', label: '跨度' },
  { key: '工作级别', label: '工作级别' },
  { key: '操作人员', label: '操作人员' },
  { key: '上次年检', label: '上次年检' },
]

const NEXT_ACTION: Record<string, string[]> = {
  正常: ['降载运行'],
  超载运行: ['安排检验'],
  检验中: ['办理停用'],
  已停用: ['恢复使用'],
}

const missingFields = computed<string[]>(() => entry.value?.missing_fields ?? [])
const missingTip = computed(() => {
  if (!missingFields.value.length) return ''
  return entry.value?.missing_tip
    ?? `缺少${missingFields.value.join('、')}，请补齐后再办理恢复使用`
})
const allowedActions = computed(() => NEXT_ACTION[entry.value?.status ?? ''] ?? [])
const formEntry = computed<CraneFormValues | null>(() => {
  if (!entry.value) return null
  const picked: CraneFormValues = {}
  for (const key of EDITABLE_KEYS) {
    const value = entry.value[key]
    if (typeof value === 'string' || typeof value === 'number') {
      ;(picked as Record<string, string | number>)[key] = value
    }
  }
  return picked
})

function statusClass(status?: string) {
  return {
    正常: 'st-ok',
    超载运行: 'st-warn',
    检验中: 'st-info',
    已停用: 'st-off',
  }[status ?? ''] ?? ''
}

function openEdit() {
  formOpen.value = true
}

function onSaved(message: string) {
  formOpen.value = false
  noticeMessage.value = message
  errorMessage.value = ''
  void load()
}

async function fillAnnual() {
  errorMessage.value = ''
  const id = Number(route.params.id)
  try {
    // 先补录年检日期，再发起恢复；任一步失败都把后端原因透传到页脚。
    const patch = await request(`${ENDPOINT}/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ values: { 上次年检: annualDate.value.trim() } }),
    })
    const patchPayload = (await patch.json()) as { ok?: boolean; message?: string }
    if (!patch.ok || patchPayload.ok === false) {
      throw new Error(patchPayload.message || '年检日期补录失败')
    }
    const action = await request(`${ENDPOINT}/${id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action: '恢复使用' }),
    })
    const actionPayload = (await action.json()) as { ok?: boolean; message?: string }
    if (!action.ok || actionPayload.ok === false) {
      throw new Error(actionPayload.message || '恢复使用失败')
    }
    noticeMessage.value = actionPayload.message || '已恢复使用'
    annualDate.value = ''
    await load()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '年检补录失败'
  }
}

async function runAction(action: string) {
  errorMessage.value = ''
  noticeMessage.value = ''
  const id = Number(route.params.id)
  try {
    const response = await request(`${ENDPOINT}/${id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = (await response.json()) as { ok?: boolean; message?: string }
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message || '起重机械动作未生效，请稍后重试')
    }
    noticeMessage.value = payload.message || ''
    await load()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '起重机械操作失败'
  }
}

async function load() {
  const id = Number(route.params.id)
  try {
    const response = await request(`${ENDPOINT}/${id}`)
    if (response.status === 404) {
      errorMessage.value = `起重机 ${id} 不存在或已归档，2 秒后返回列表`
      window.setTimeout(() => router.push('/crane'), 2000)
      return
    }
    if (!response.ok) {
      throw new Error('起重机详情读取失败')
    }
    entry.value = (await response.json()) as DetailRow
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '起重机详情读取失败'
  }
}

watch(() => route.params.id, () => void load())
void load()
</script>
