<template>
  <section class="page" data-module="crane">
    <header class="page-head">
      <div>
        <h2>起重机械管理</h2>
        <p class="page-desc">维护起重机，围绕起重机编号、起重机类型、额定起重量、跨度做登记、筛选与状态流转。台账按额定起重量从大到小排列。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记起重机</button>
        <button class="btn" type="button" @click="exportRows">导出起重机械清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>起重机编号</span>
        <input v-model="keyword" placeholder="按起重机编号检索" />
      </label>
      <label class="filter-item">
        <span>状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>年检/明细</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <template v-if="column === '上次年检' && isBlank(row[column])">
              <span class="error-text">缺上次年检</span>
            </template>
            <template v-else-if="column === '起重机状态'">
              <span :class="['status-tag', statusClass(row)]">{{ row[column] }}</span>
            </template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td>
            <button class="link" type="button" @click="openDetail(row)">
              {{ missingFields(row).length ? '补齐年检' : '查看明细' }}
            </button>
          </td>
          <td class="row-actions">
            <button
              v-for="action in availableActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无起重机械数据，可先登记起重机</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条起重机械记录（顺序由后端按额定起重量排序，重新进入页面不会回到旧顺序）</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="detailRow" class="modal-mask" @click.self="closeDetail">
      <div class="modal-card">
        <h3>起重机明细 · {{ detailRow['起重机编号'] }}</h3>
        <p v-if="missingFields(detailRow).length" class="error-text">
          缺少必填字段：{{ missingFields(detailRow).join('、') }}，请补齐后再安排检验、办理停用或恢复使用
        </p>
        <dl class="detail-grid">
          <template v-for="field in detailFields" :key="field">
            <dt>{{ field }}</dt>
            <dd :class="{ 'error-text': field === '上次年检' && isBlank(detailRow[field]) }">
              <template v-if="field === '上次年检' && isBlank(detailRow[field])">未填写</template>
              <template v-else>{{ detailRow[field] || '—' }}</template>
            </dd>
          </template>
        </dl>

        <div v-if="isStopped(detailRow)" class="detail-form">
          <label>
            <span>补齐上次年检</span>
            <input v-model="inspectionDate" placeholder="如 2026-09-30" />
          </label>
          <button class="btn primary" type="button" @click="restoreWithInspection(detailRow)">补齐年检并恢复使用</button>
        </div>

        <div class="modal-actions">
          <button class="btn" type="button" @click="closeDetail">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/crane'
const columns = ['起重机编号', '起重机类型', '额定起重量', '跨度', '工作级别', '操作人员', '上次年检', '起重机状态']
const detailFields = columns
const statuses = ['正常', '超载运行', '检验中', '已停用']
// 与后端 AVAILABLE_ACTIONS 对齐：状态只能顺着往下走，已停用只能补齐年检后恢复。
const actionByStatus: Record<string, string[]> = {
  正常: ['降载运行'],
  超载运行: ['安排检验'],
  检验中: ['办理停用'],
  已停用: ['恢复使用'],
}

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')

const detailRow = ref<Row | null>(null)
const inspectionDate = ref('')

const stats = computed(() => [
  { label: '正常起重机', value: rows.value.filter((row) => row['起重机状态'] === '正常').length },
  { label: '超载起重机', value: rows.value.filter((row) => row['起重机状态'] === '超载运行').length },
  { label: '检验起重机', value: rows.value.filter((row) => row['起重机状态'] === '检验中').length },
  { label: '已停用', value: rows.value.filter((row) => row['起重机状态'] === '已停用').length },
])

function isBlank(value: unknown): boolean {
  return value === null || value === undefined || String(value).trim() === ''
}

function missingFields(row: Row): string[] {
  return Array.isArray(row['缺失字段']) ? (row['缺失字段'] as string[]) : []
}

function availableActions(row: Row): string[] {
  return actionByStatus[String(row['起重机状态'])] ?? []
}

function isStopped(row: Row): boolean {
  return row['起重机状态'] === '已停用'
}

function statusClass(row: Row): string {
  const status = String(row['起重机状态'])
  if (status === '超载运行') return 'status-danger'
  if (status === '检验中') return 'status-warn'
  if (status === '已停用') return 'status-muted'
  return 'status-ok'
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '起重机登记入口尚未接入审批流'
}

function openDetail(row: Row) {
  detailRow.value = row
  inspectionDate.value = String(row['上次年检'] ?? '')
}

function closeDetail() {
  detailRow.value = null
  inspectionDate.value = ''
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  const values: Record<string, string> = { action }

  if (action === '降载运行') {
    const input = window.prompt('降载后的额定起重量（单位 t，需小于当前值）', String(row['额定起重量'] ?? ''))
    if (input === null) return
    values['额定起重量'] = input.trim()
  }
  if (action === '恢复使用' && missingFields(row).length) {
    openDetail(row)
    errorMessage.value = '缺少必填字段：上次年检，请先在明细里补齐年检日期再恢复使用'
    return
  }

  await submitAction(row.id as number, values)
}

async function restoreWithInspection(row: Row) {
  errorMessage.value = ''
  if (!inspectionDate.value.trim()) {
    errorMessage.value = '缺少必填字段：上次年检'
    return
  }
  await submitAction(row.id as number, { action: '恢复使用', 上次年检: inspectionDate.value.trim() })
  closeDetail()
}

async function submitAction(entryId: number, values: Record<string, string>) {
  try {
    const response = await request(`${ENDPOINT}/${entryId}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = (await response.json().catch(() => null)) as { ok?: boolean; message?: string } | null
    // 后端会把状态回退、跳步、缺年检等违规操作拦下并给出原因，必须原样展示。
    if (!response.ok || !payload || payload.ok === false) {
      throw new Error(payload?.message || '起重机械动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '起重机械操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value.trim()) query.set('keyword', keyword.value.trim())
  if (statusFilter.value) query.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('起重机列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '起重机械列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.status-tag {
  display: inline-block;
  padding: 0 8px;
  border-radius: 10px;
  font-size: 12px;
  line-height: 20px;
}
.status-ok {
  background: #e6f7ec;
  color: #1d7a43;
}
.status-danger {
  background: #fdeaea;
  color: #c0392b;
}
.status-warn {
  background: #fdf3e0;
  color: #b9770e;
}
.status-muted {
  background: #eef0f2;
  color: #7f8c8d;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal-card {
  width: 560px;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 64px);
  overflow: auto;
  background: #fff;
  border-radius: 8px;
  padding: 20px 24px;
}
.detail-grid {
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: 8px 12px;
  margin: 12px 0;
}
.detail-grid dt {
  color: #64748b;
}
.detail-grid dd {
  margin: 0;
}
.detail-form {
  display: flex;
  gap: 12px;
  align-items: flex-end;
  border-top: 1px solid #eef0f2;
  padding-top: 12px;
}
.detail-form label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
