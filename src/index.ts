import { Context, h, Schema } from "koishi";
import { GetResponse } from "./types";
// export const using = ['__cron__']
import {} from "koishi-plugin-cron";
import { channel } from "diagnostics_channel";
export const using = ["cron", "database"];

export const name = "dailyarxiv";
const PAPER_TABLE_NAME = "dailyarxiv";
const REQ_TABLE_NAME = "dailyarxiv_req";

declare module "koishi" {
  interface Tables {
    [PAPER_TABLE_NAME]: ArxivMeta;
    [REQ_TABLE_NAME]: Req;
  }
}

export interface ArxivMeta {
  id?: number;
  title: string;
  authors: string[];
  abs: string;
  link: string;
  created_at: string;
}

export interface Req {
  time: string;
  req_n_res: [string, string][];
}

export interface Config {
  watingMsg?: boolean;
  endPoint: string;
  openai_base_url: string;
  openai_api_key: string;
  model: string;
  interests: string[];
}

export const Config: Schema<Config> = Schema.object({
  watingMsg: Schema.boolean()
    .description("等待响应前是否提示。")
    .default(false),
  endPoint: Schema.string()
    .description("服务器地址")
    .default("http://127.0.0.1:8007/daily"),
  openai_base_url: Schema.string().description("openai base url"),
  openai_api_key: Schema.string().description("openai api key"),
  model: Schema.string().description("openai model"),
  interests: Schema.array(Schema.string()).description("兴趣列表"),
});

export function apply(ctx: Context, config: Config) {
  // write your plugin here
  ctx.logger("dailyarxiv").info("dailyarxiv plugin loaded");

  ctx.model.extend(PAPER_TABLE_NAME, {
    id: 'unsigned',
    title: 'text',
    authors: 'list',
    abs: 'text',
    link: 'text',
    created_at: 'text',
  }, {
    primary: "id",
    autoInc: true,
  });

  ctx.model.extend(REQ_TABLE_NAME, {
    time: 'text',
    req_n_res: 'json',
  }, {
    primary: "time",
  });
  
  const getRes = async (): Promise<string> => {
    let res: GetResponse = await ctx.http.axios(config.endPoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      timeout: 300000,
      data: {
        interests: config.interests,
        openai_api_base: config.openai_base_url,
        openai_api_key: config.openai_api_key,
        model: config.model,
      },
    });
    if (res) return res.data["message"];
    throw new Error();
  };

  async function handleDaily({ session }) {
    console.info("dailyarxiv");
    if (config.watingMsg) session.send(session.text(".waiting"));
    try {
      await session.send(
        h("quote", { id: session.messageId } + (await getRes()))
      );
    } catch (e) {
      return session.send(session.text(".error"));
    }
  }

  ctx.command("dailyArxiv").action(handleDaily);

  ctx.command("test").action(async ({ session }) => {
    session.send("test");
    // let channels = await ctx.database.get("channel", {});
    console.info(console.info(ctx.bots));
    ctx.database.create(REQ_TABLE_NAME, {
      time: new Date().toLocaleString(),
      req_n_res: [["a", "b"], ["b", "c"]],
    });
  });

  async function getBot() {
    let channels = await ctx.database.get("channel", {});
    let bot = undefined,
      channelId = undefined,
      guildId = undefined;
    for (let channel of channels) {
      channelId = channel["id"];
      guildId = channel["guildId"];
      let platform = channel["platform"];
      let selfId = channel["assignee"];

      for (let _bot of ctx.bots) {
        if (_bot.platform === platform && _bot.selfId === selfId) {
          bot = _bot;
          break;
        }
      }

    }
    return {bot, channelId, guildId};
  }

  ctx.cron("15 23 * * *", async () => {
    console.log("dailyarxiv cron");
    let {bot, channelId, guildId} = await getBot(),
      dailyNews = undefined;

    if (bot === undefined) {
      dailyNews = "error";
    } else {
      dailyNews = await getRes();
    }
    console.info(dailyNews);

    if (dailyNews === "error") {
      ctx.logger("dailyarxiv").warn("get daily news error");
      bot?.sendMessage(channelId, "呜呜呜论文推送姬出错啦——", guildId);
    } else {
      ctx.logger("dailyarxiv").info("get daily news success");
      bot?.sendMessage(channelId, dailyNews, guildId);
      // let bot = await getBot();
      // let channels = await ctx.database.get("channel", {});
      // for (let channel of channels) {
      //   let channelId = channel["id"],
      //     platform = channel["platform"],
      //     selfId = channel["assignee"],
      //     guildId = channel["guildId"];
      //   let bot = undefined;
      //   for (let _bot of ctx.bots) {
      //     if (_bot.platform === platform && _bot.selfId === selfId) {
      //       bot = _bot;
      //       break;
      //     }
      //   }
      //   console.info(bot);
      //   bot?.sendMessage(channelId, dailyNews, guildId);
      // }
    }
  });
}
