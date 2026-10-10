import type { Language } from '../api/practice';

const labels = {
  zh: {
    discover: '找教材', study: '学习进度', tutor: '在线辅导', search: '搜索教材', searchHint: '书名、科目或关键词', level: '学段', grade: '年级', subject: '科目', publisher: '出版社', all: '全部', more: '加载更多', open: '打开教材', back: '返回目录', noBooks: '没有找到教材，请调整筛选条件。', plan: '学习计划', bookLevel: '全书练习', generate: '生成练习', generating: '正在生成练习', cancel: '取消生成', retry: '重试', questionCount: '题数', difficulty: '难度', introductory: '入门', standard: '标准', challenge: '挑战', start: '开始练习', answer: '提交答案', answerField: '答案', chooseOne: '选择一项', trueFalse: '判断对错', trueLabel: '正确', falseLabel: '错误', giveUp: '放弃并查看答案', next: '下一题', feedback: '反馈', hint: '提示', revealed: '参考答案', sources: '教材证据', ask: '询问助教', askHint: '针对当前题目提问', liveChat: '课程对话', send: '发送', resume: '继续学习', emptyProgress: '还没有练习记录。', progress: '已完成', error: '操作失败', report: '报告问题', reportReason: '问题类型', reportIncorrect: '内容错误', reportAmbiguous: '表述含糊', reportUnsafe: '不适宜内容', reportDetail: '补充说明（可选）', language: '语言', aiNotice: 'AI 生成的学习辅助内容，请对照教材核查。', loading: '加载中…', course: '课程', question: '题目', selectBookForTutor: '请先从教材目录打开一本书，或恢复之前的学习。', correct: '回答正确', incorrect: '尚未答对', provisional: '需要进一步核查', gaveUp: '已放弃', status: '状态', statusNotStarted: '未开始', statusInProgress: '学习中', statusCompleted: '已完成', sourceVersion: '教材版本', reportSent: '报告已提交。', reply: '助教回答', noCitation: '本次回答没有教材引用，请谨慎核查。', clear: '清除继续学习位置',
  },
  en: {
    discover: 'Books', study: 'Progress', tutor: 'Tutor', search: 'Search books', searchHint: 'Title, subject or keyword', level: 'Level', grade: 'Grade', subject: 'Subject', publisher: 'Publisher', all: 'All', more: 'Load more', open: 'Open book', back: 'Back to catalog', noBooks: 'No books found. Try another filter.', plan: 'Study plan', bookLevel: 'Whole-book practice', generate: 'Generate practice', generating: 'Generating practice', cancel: 'Cancel generation', retry: 'Retry', questionCount: 'Questions', difficulty: 'Difficulty', introductory: 'Introductory', standard: 'Standard', challenge: 'Challenge', start: 'Start practice', answer: 'Submit answer', answerField: 'Answer', chooseOne: 'Choose one', trueFalse: 'True or false', trueLabel: 'True', falseLabel: 'False', giveUp: 'Give up and reveal answer', next: 'Next question', feedback: 'Feedback', hint: 'Hint', revealed: 'Suggested answer', sources: 'Textbook evidence', ask: 'Ask the tutor', askHint: 'Ask about this question', liveChat: 'Course chat', send: 'Send', resume: 'Resume study', emptyProgress: 'No practice history yet.', progress: 'Completed', error: 'Operation failed', report: 'Report issue', reportReason: 'Issue type', reportIncorrect: 'Incorrect content', reportAmbiguous: 'Ambiguous wording', reportUnsafe: 'Unsafe content', reportDetail: 'More detail (optional)', language: 'Language', aiNotice: 'AI-generated learning guidance. Check against the textbook.', loading: 'Loading…', course: 'Course', question: 'Question', selectBookForTutor: 'Open a book from the catalog or resume a previous session first.', correct: 'Correct', incorrect: 'Not yet correct', provisional: 'Needs review', gaveUp: 'Gave up', status: 'Status', statusNotStarted: 'Not started', statusInProgress: 'In progress', statusCompleted: 'Completed', sourceVersion: 'Textbook version', reportSent: 'Report submitted.', reply: 'Tutor response', noCitation: 'This answer has no textbook citation; verify it carefully.', clear: 'Clear resume position',
  },
} as const;

export type Labels = Record<keyof typeof labels.zh, string>;
export function getLabels(language: Language): Labels {
  if (language === 'en') return labels.en;
  if (language === 'bilingual') {
    const result = {} as Labels;
    (Object.keys(labels.zh) as (keyof Labels)[]).forEach((key) => { result[key] = `${labels.zh[key]} / ${labels.en[key]}`; });
    return result;
  }
  return labels.zh;
}

const key = 'hiruzen.language.v1';
export function loadLanguage(): Language {
  try {
    const saved = window.localStorage.getItem(key);
    return saved === 'en' || saved === 'bilingual' ? saved : 'zh';
  } catch { return 'zh'; }
}
export function saveLanguage(language: Language): void {
  try { window.localStorage.setItem(key, language); } catch { /* storage may be unavailable */ }
}
