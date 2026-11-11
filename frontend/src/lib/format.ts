const won = new Intl.NumberFormat("ko-KR");

export const formatWon = (value: number) => won.format(value);
export const formatRate = (bps: number) => (bps / 100).toFixed(2);
export const reserveLabel = (reserveType: string) => reserveType === "free" ? "자유적립" : "정액적립";
