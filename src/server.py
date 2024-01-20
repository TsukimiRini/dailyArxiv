from langchain_community.document_loaders import AsyncChromiumLoader
from html.parser import HTMLParser
from langchain.schema import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
import asyncio
import uvicorn
from fastapi import FastAPI, Body

app = FastAPI()


class ArxivParser(HTMLParser):
    result_list = []
    cur_result = None
    cur_ele = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "class" in attrs.keys():
            if "arxiv-result" in attrs["class"]:
                self.cur_result = {
                    "title": "",
                    "authors": "",
                    "abstract": "",
                    "link": "",
                    "tags": [],
                }
                self.result_list.append(self.cur_result)
            elif "title" in attrs["class"]:
                self.cur_ele = "title"
            elif "authors" in attrs["class"]:
                self.cur_ele = "authors"
            elif "abstract-full" in attrs["class"]:
                self.cur_ele = "abstract"
            elif "tag is-small" in attrs["class"]:
                if self.cur_result is None:
                    return
                self.cur_result["tags"].append(attrs["data-tooltip"])
        if "href" in attrs.keys() and self.cur_result is not None:
            href = attrs["href"]
            if href.startswith("https://arxiv.org/pdf/"):
                self.cur_result["link"] = href

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" or tag == "div":
            self.cur_ele = None

    def handle_data(self, data: str) -> None:
        data = data.strip()
        if self.cur_result is None:
            return
        if self.cur_ele is not None:
            if self.cur_ele == "title":
                self.cur_result["title"] = data
            elif self.cur_ele == "authors" and data != "Authors:":
                self.cur_result["authors"] += data
            elif self.cur_ele == "abstract" and data != "△ Less":
                self.cur_result["abstract"] += data


class ArxivLoader(AsyncChromiumLoader):
    def __init__(self, urls):
        super().__init__(urls)
        self.parser = ArxivParser()

    def set_urls(self, urls):
        self.urls = urls
        self.parser.result_list = []
        self.parser.cur_result = None
        self.parser.cur_ele = None

    async def load(self):
        self.content = await self.ascrape_playwright(self.urls[0])
        # content = super().load()[0].page_content
        self.parser.feed(self.content)
        return self.parser.result_list


import regex


class ArxivOutputParser(StrOutputParser):
    def parse(self, output):
        pattern = regex.compile(r"\[[\d,]+\]")
        output = pattern.findall(output)
        recommended = []
        for i in range(len(output)):
            output[i] = output[i].replace("[", "").replace("]", "").split(",")
            output[i] = [int(j) - 1 for j in output[i]]
            recommended += output[i]
        return recommended


def prompt_construct(results, interests):
    for result in results:
        result["tags"] = ", ".join(result["tags"])
    result_template = """Title: {title}
Abstract:
{abstract}"""
    results = [result_template.format(**result) for result in results]
    system_message = SystemMessage(
        content="You are a helpful assistant. You are helping a busy researcher by selecting valuable papers that he may have interest in from some candidate papers."
    )

    prompt_template = """I have found {num_results} papers from the paper database. Please help me to choose some of them to read according to my interests by giving your response in a standard format.

# Candidate Papers
{candidate_papers}

# Intereted Topics
{interested_topics}

# Response Format
You should read through the papers' title and abstract carefully to identify whether the paper is a good choice for me.
You should FIRST give your reasons for recommending or rejecting the paper in the format of a numbered LISTING. Please state carefully about whether the selected papers have relationship to my interets. Don't be too verbose, though (at most two sentences for each paper are fine).
THEN you should conclude your recommendation in the format of an ARRAY. For example, if you want to choose the first and the third paper, you can give a "[1,3]". However, if you want to choose all of them, you can give a "[all]"; if you don't want to choose any of them, you can give a "[none]".
"""
    interested_topics = ""
    for interest in interests:
        interested_topics += f"""- {interest}
"""

    result_groups = [results[i : i + 5] for i in range(0, len(results), 5)]
    prompts = []
    for i, group in enumerate(result_groups):
        candidate_papers = ""
        for j, result in enumerate(group):
            candidate_papers += f"""
## {j + 1}
{result}
"""
        batch_prompt = prompt_template.format(
            num_results=len(group),
            candidate_papers=candidate_papers,
            interested_topics=interested_topics,
        )

        prompts.append([system_message, HumanMessage(content=batch_prompt.strip())])

    return prompts


def get_model(openai_api_base, openai_api_key, model="gpt-3.5-turbo-1106"):
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        openai_api_base=openai_api_base, openai_api_key=openai_api_key, model=model
    )
    return llm


import time


@app.post("/daily")
async def retrive_daily(body: dict = Body(...)):
    interests = body["interests"]
    openai_api_base = body["openai_api_base"]
    openai_api_key = body["openai_api_key"]
    model = body["model"]

    res = ""
    yesterday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    the_day_before_yesterday = time.strftime(
        "%Y-%m-%d", time.localtime(time.time() - 86400 * 2)
    )
    # url = f"https://arxiv.org/search/advanced?advanced=&terms-0-operator=AND&terms-0-term=Artificial+Intelligence&terms-0-field=all&terms-1-operator=OR&terms-1-term=Software+Engineering&terms-1-field=all&classification-computer_science=y&classification-physics_archives=all&classification-include_cross_list=include&date-year=&date-filter_by=date_range&date-from_date={the_day_before_yesterday}&date-to_date={yesterday}&date-date_type=submitted_date_first&abstracts=show&size=200&order=-announced_date_first"
    url = f"https://arxiv.org/search/advanced?advanced=&terms-0-operator=AND&terms-0-term=Artificial+Intelligence&terms-0-field=all&terms-1-operator=OR&terms-1-term=Software+Engineering&terms-1-field=all&classification-computer_science=y&classification-physics_archives=all&classification-include_cross_list=include&date-year=&date-filter_by=date_range&date-from_date=2024-01-05&date-to_date=2024-01-06&date-date_type=submitted_date_first&abstracts=show&size=200&order=-announced_date_first"

    print(url)

    try:
        loader = ArxivLoader([url])
        results = await loader.load()
        cnt = 3
        while len(results) == 0 and cnt > 0:
            print("retry", loader.content)
            cnt -= 1
            results = await loader.load()

        if len(results) == 0:
            raise Exception("no results")

        prompts = prompt_construct(results, interests=interests)
        output_parser = ArxivOutputParser()
        llm = get_model(
            openai_api_base=openai_api_base, openai_api_key=openai_api_key, model=model
        )
        responses = await llm.abatch(prompts)
        responses = [output_parser.parse(response.content) for response in responses]
        print(responses)
        selected = [
            idx * 5 + response[i]
            for idx, response in enumerate(responses)
            for i in range(len(response))
        ]
        for idx in selected:
            res += f"""======
{results[idx]["link"]}
{results[idx]["title"]}
"""
    # {results[idx]["abstract"]}
    # """
    except Exception as e:
        print(e)
        res = "error"

    print(res)
    return {"message": res}


@app.get("/ping")
def ping():
    return {"message": "pong"}


if __name__ == "__main__":
    HOST = "127.0.0.1"
    PORT = 8007
    uvicorn.run(app, host=HOST, port=PORT)
