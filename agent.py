from nearai.agents.environment import Environment


def run(env: Environment):
    # Your agent code here
    prompt = {"role": "system", "content": "You are a quiz generator. When provided a topic ,create the quiz based off that and when you are not, create a quiz with one answer correct and 3 options wrong"}
    result = env.completion([prompt] + env.list_messages())
    env.add_reply(result)
    env.request_user_input()

run(env)

