export type OutputLimitAction = "stop" | "retry" | "send_message";

export type OutputLimitPolicy = {
  output_limit_action: OutputLimitAction;
  output_limit_save_partial: boolean;
  output_limit_message: string;
  output_limit_max_recoveries: number | null;
};

export const DEFAULT_OUTPUT_LIMIT_MESSAGE = "上一轮生成达到单次输出上限，任务尚未完成。请根据当前会话中的已有内容和工具结果继续完成原任务，避免重复已完成的内容。未完整生成的工具调用没有执行，如仍需要，请重新生成完整调用。";

export const DEFAULT_OUTPUT_LIMIT_POLICY: OutputLimitPolicy = {
  output_limit_action: "retry",
  output_limit_save_partial: false,
  output_limit_message: DEFAULT_OUTPUT_LIMIT_MESSAGE,
  output_limit_max_recoveries: null,
};
