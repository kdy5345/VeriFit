import { afterEach, expect, it, vi } from "vitest";
import { askAgent, restoreConversation, compareScenarios } from "./api";

afterEach(() => vi.unstubAllGlobals());

it("실제 요청 경로·본문·세션을 서버 계약대로 전달한다", async () => {
  const fetchMock = vi.fn().mockImplementation(async () => new Response(JSON.stringify({thread_id: "t"}), {status: 200}));
  vi.stubGlobal("fetch", fetchMock);
  await askAgent("월 30만원 1년", "t");
  expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/v1\/ask$/);
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({message: "월 30만원 1년", thread_id: "t"});
  await restoreConversation("a/b");
  expect(fetchMock.mock.calls[1][0]).toMatch(/a%2Fb$/);
  const profile = {monthly_deposit_won: 300000, term_months: 12, facts: {}};
  await compareScenarios(profile, {...profile, term_months: 24});
  expect(JSON.parse(fetchMock.mock.calls[2][1].body).scenarios[0].profile.term_months).toBe(24);
});

it("HTTP 오류를 정상 결과로 취급하지 않는다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({detail: "서비스 오류"}), {status: 503})));
  await expect(askAgent("조건")).rejects.toThrow("서비스 오류");
});

it("JSON이 아닌 응답을 안전하게 거절한다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("not-json", {status: 200})));
  await expect(askAgent("조건")).rejects.toThrow("서버 응답을 읽지 못했습니다.");
});
