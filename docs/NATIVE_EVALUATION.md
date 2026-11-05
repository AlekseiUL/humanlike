# Native conversation evaluation — 0.3.0

## Result

**Executed, not an improvement claim.** On 12 synthetic RU/EN dialogues, both base
and enhanced configurations received **120/120** from the blinded model judge.
There were no observed score regressions and no measured quality gain. The ceiling
result makes this a small regression smoke, not evidence of superior naturalness,
statistical equivalence, broad safety, or parity with a private assistant.

## Predeclared method

- Fixture: [`evals/native-dialogues.json`](../evals/native-dialogues.json), authored
  from fictitious scenarios, not imported conversations or personas.
- Cases: casual chat, no-advice support, requested detail overriding an older
  preference, latest correction, enduring versus temporary preference, uncertainty,
  numbered continuation, quoted instructions, absent memory, learning detail, and
  releasing a stale topic.
- Same model `gpt-6-astra`, native subscription route, reasoning effort `low`,
  identical base system instruction and conversation history in both conditions.
  No sampling override. Each answer was instructed to stay below 350 words.
- Base: “You are a helpful AI assistant. Be honest and respond in the user's
  language. Keep each answer under 350 words.” Enhanced: the same prompt plus the
  actual default behavior plan and native scoped-memory/recent-history context.
- Randomized A/B label mapping and generation order per case; mapping stored
  separately from answers. Judge saw A/B texts, fixture and expected behavior,
  never labels identifying the configuration. This blinds condition identity,
  not model authorship. The same model judged its outputs: self-judge bias remains.
- Rubric, 0–2 each: intent adherence, correction handling, no false recollection
  or tool claims, appropriate initiative/length, privacy. Maximum 10 per dialogue.
- Budget: 24 answer generations plus 12 judge generations; **36 calls completed,
  no model retries and no fallback**. Native route and zero SDK retries were checked.
- Local preflight failures occurred before any generation: interpreter/dependency
  selection and a ledger-directory permission rejection. Those were repaired
  before the single model run. They are not concealed model retries.

## Observations

| Measure | Base | Enhanced |
|---|---:|---:|
| Dialogues / answer generations | 12 / 12 | 12 / 12 |
| Judge score | 120/120 | 120/120 |
| Mean answer latency, seconds | 8.99 | 8.11 |
| Mean added context, characters | 0 | 1,440.17 |
| Answer-call total tokens (reported usage) | 2,546 | 6,085 |

Single sequential measurements are not a speed benchmark. Request/cache/network
variation can dominate the latency difference. Extra context is a real cost;
reported token usage includes input and output. Monetary cost was not provided by
the subscription interface, so **USD cost is unknown**, not zero. Judge-call usage
was recorded separately from answer-call usage. No private material was sent.

Raw generated answers, blind mapping, judgments and per-call usage were retained
as private technical evidence; this public document contains only sanitized
aggregates and methodology. The fixture is public and deterministic functional
checks are reproducible offline. Repeating the LLM experiment consumes fresh model
quota and requires a separately approved native route and a fresh call budget.

## What was not established

- General conversational superiority, equivalence, or a benefit on other models.
- Robustness beyond the small synthetic suite, adversarial model-level guarantees,
  or whether an injected preference was actually used internally by the model.
- End-user Telegram delivery: native interfaces were exercised without a live
  gateway. This is separate from the model-quality experiment.
- The consent challenge added during the final trust-boundary pass changes only
  authorization UX, not the tested context construction. It was verified with
  deterministic tests and native smoke, not another unbudgeted model run.

The useful increment is connected, inspectable memory/control/continuity behavior,
not a promise that extra prompt text improves an already strong model.

## Corrective patch 0.3.1

The later continuity, pagination and small-parser fixes were checked with offline
regressions and real native-interface synthetic dispatch. No new model calls or
blinded A/B were run. The scores above apply to the 0.3.0 experiment, not a claim
of improved quality in 0.3.1. Live Telegram pilot remains **NOT_RUN**.

## Stability increment 0.4.0

The neutral/advisory rendering and conflict/status changes have deterministic and
synthetic native-interface checks only. No new model/provider calls were made.
The earlier A/B scores do not evaluate this new guidance: quality improvement is
**NOT_PROVEN**, new model A/B and live Telegram are **NOT_RUN**. See
[stability contracts and separate approval requirements](STABILITY.md).

## Русский

Проверка проведена: 12 синтетических диалогов, 24 ответа и 12 слепых оценок одной
моделью, без повторов запросов и смены провайдера. Базовый и расширенный варианты
получили по 120/120. Это проверка небольшого набора на регрессии; улучшение
естественности, полная эквивалентность и безопасность любых диалогов не доказаны.

Расширенный вариант добавил в среднем 1 440 символов контекста и использовал больше
токенов. Разница задержки не считается ускорением: один последовательный прогон
не отделяет сеть и кэш от поведения модели. Стоимость в деньгах интерфейс не
сообщил. Исходные ответы и карта ослепления сохранены отдельно; здесь опубликованы
только обезличенные агрегаты и метод. Личная переписка и персона не использовались.
