/**
 * ashare-vp Cloudflare Worker
 *
 * - fetch: 把网页请求交给静态资源绑定 ASSETS，保持现有站点行为不变。
 * - scheduled: 每个交易日 07:30 UTC（北京时间 15:30）调用 GitHub
 *   workflow_dispatch，触发 daily.yml 的 close 任务。
 *
 * 需要配置：
 *   - Secret: GITHUB_TOKEN（Fine-grained PAT，Actions: Write）
 *   - vars: GITHUB_OWNER / GITHUB_REPO / GITHUB_WORKFLOW / GITHUB_REF
 */

const DEFAULTS = {
  owner: "lx7575000",
  repo: "ashare-vp",
  workflow: "daily.yml",
  ref: "main",
};

function setting(env, key, fallback) {
  const value = env && env[key];
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

async function dispatchClose(env) {
  const token = setting(env, "GITHUB_TOKEN", "");
  if (!token) {
    throw new Error("GITHUB_TOKEN secret is not configured");
  }

  const owner = setting(env, "GITHUB_OWNER", DEFAULTS.owner);
  const repo = setting(env, "GITHUB_REPO", DEFAULTS.repo);
  const workflow = setting(env, "GITHUB_WORKFLOW", DEFAULTS.workflow);
  const ref = setting(env, "GITHUB_REF", DEFAULTS.ref);
  const url = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflow}/dispatches`;

  const response = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "ashare-vp-cloudflare-cron",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      ref,
      inputs: {
        session: "close",
        // force 不传，workflow 默认 false；避免把布尔值序列化成字符串。
      },
    }),
  });

  if (response.status !== 204) {
    const detail = await response.text();
    throw new Error(
      `GitHub workflow_dispatch failed: ${response.status} ${detail.slice(0, 500)}`,
    );
  }

  console.log(`dispatched ${owner}/${repo} ${workflow}@${ref} session=close`);
}

export default {
  async fetch(request, env) {
    return env.ASSETS.fetch(request);
  },

  async scheduled(controller, env) {
    console.log(`cron triggered: ${controller.cron}`);
    await dispatchClose(env);
  },
};
