import React from "react";

const DEFAULT_QUESTIONS = [
  "汇总一下本月所以酒店的经营情况",
  "广州丽思卡尔顿酒店3月的收入情况怎么样？",
  "看一下江门嘉华酒店3月的经营情况",
  "本月总收入同比如何？",
  "生成华南区本月经营摘要"
];

export function QuickQuestions({
  onSelect,
  activeQuestion,
  disabled = false,
  questions
}: {
  onSelect: (q: string) => void;
  activeQuestion?: string;
  disabled?: boolean;
  questions?: string[];
}) {
  const finalQuestions = questions?.length ? questions : DEFAULT_QUESTIONS;
  return (
    <div className="panel">
      <div className="section-head">
        <div>
          <div className="panel-title">快捷提问</div>
          <div className="section-desc">像聊天一样点一个就发，不需要先展开复杂参数。</div>
        </div>
      </div>
      <div className="chips">
        {finalQuestions.map((q, index) => (
          <button
            type="button"
            className={`chip ${activeQuestion === q ? "active" : ""}`}
            key={q}
            onClick={() => onSelect(q)}
            disabled={disabled}
            data-testid={`quick-question-${index}`}
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
