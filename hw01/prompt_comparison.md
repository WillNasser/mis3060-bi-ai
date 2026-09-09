# Prompt Comparison: Communicating Data Limitations to a Non-Technical Audience

Three prompting strategies were used to ask Claude the same underlying question — how a BI analyst should communicate data limitations to a non-technical audience — to compare how prompt design changes the usefulness of the output.

---

## Strategy 1: Direct/Baseline Prompt

### Complete Prompt

```
How should a BI analyst communicate data limitations to a non-technical audience?
```

### First 150 Words of Response

> The core challenge is translating statistical caveats into language that changes how someone acts on the numbers, without either overwhelming them or making the analysis seem unreliable. A few principles tend to matter most: Lead with the takeaway, then the caveat. Non-technical stakeholders want to know what the data means for a decision before they want to know why it might be imperfect. Something like "Regional sales grew 12%, though this is based on a small sample from two stores, so treat it as directional rather than precise" puts the actionable insight first and the limitation second, rather than burying the finding under a wall of methodology. Translate statistical concepts into business consequences. Instead of saying "margin of error is +/-8%," say "the actual number could be anywhere from 4% to 20% growth, so we wouldn't bet the budget on the 12% figure alone." Instead of "n=14," say "we only...

### Evaluation

**What it did well:** This prompt produced the most comprehensive answer of the three, covering eight distinct principles (leading with the takeaway, translating stats into business consequences, using plain-language confidence tiers, showing rather than stating limitations, naming what's missing from the data, avoiding false precision, tying caveats to recommendations, and staying consistent across reports). The examples were clear and the structure was logical and easy to skim.

**What was missing or generic:** Because the prompt gave no audience, industry, or scenario, the response defaulted to generic best-practice advice that could apply to almost any BI context. There's no sense of who is in the room, what's at stake, or how the analyst should adapt tone for a specific type of stakeholder. It reads like a well-organized blog post rather than guidance tailored to a real presentation, and with eight principles and no explicit ranking, a reader still has to decide what matters most for their situation.

---

## Strategy 2: Role/Persona Prompt

### Complete Prompt

```
You are a senior credit risk analyst presenting to a portfolio committee of three senior executives, now answer this question:

* "How should a BI analyst communicate data limitations to a non-technical audience?"
```

### First 150 Words of Response

> When a BI analyst is presenting to a portfolio committee rather than to other analysts, the core discipline is to separate the finding from the confidence in the finding, and to spend at least as much effort on the second part as the first. A few principles I'd apply, and that I hold my own team to: Lead with the business consequence, not the technical caveat. Executives don't need to hear "the sample size for the subprime cohort was 340 accounts with a 15% missing-field rate." They need to hear "our subprime delinquency estimate could be off by as much as 2 points in either direction — treat this as directional, not a number to underwrite against." The technical detail belongs in an appendix or a footnote the analyst can defend if asked, not in the headline. Translate uncertainty into decision language, not statistical language. Confidence intervals, p-values, and data-lineage...

### Evaluation

**What it did well:** Assigning a persona and an audience (a credit risk analyst presenting to an executive portfolio committee) sharpened the examples considerably — they shifted from generic "sales grew 12%" language to domain-specific, boardroom-relevant scenarios like subprime delinquency estimates and underwriting decisions. The response also added a genuinely new idea not present in Strategy 1: state explicitly what the limitation does and doesn't change about the recommendation, which is a more sophisticated, decision-oriented framing than a simple caveat.

**What was missing or generic:** The response still followed nearly the same structural skeleton as Strategy 1 (translate to consequence, use visual/verbal tiers, don't bury the caveat, be proactive), so several points are restatements rather than genuinely new insight. Because the persona was narrow (credit risk, portfolio committee), the guidance is less directly transferable to a BI analyst in another industry, and the response never fully stays "in character" — it drifts back into generic listicle advice by the end rather than continuing to speak as a credit risk analyst throughout.

---

## Strategy 3: Format-Constrained Prompt

### Complete Prompt

```
How should a BI analyst communicate data limitations to a non-technical audience?
your answer should include 3 main points as well as examples
```

### First 150 Words of Response

> A BI analyst's job isn't done when the dashboard ships — it's done when the audience understands what the numbers can and can't tell them. Three things matter most for getting that across to a non-technical audience. 1. Translate the limitation into a business consequence, not a technical caveat. Saying "the sample size is small" or "there's a 15% null rate in the source table" means little to someone outside data. What lands is what that limitation means for the decision they're about to make. Instead of "our attribution model has known gaps in cross-device tracking," say "we're likely undercounting mobile-to-desktop purchases, so the true conversion rate is probably higher than the 2.1% shown — treat this as a floor, not the full picture." The technical detail can go in a footnote or appendix for anyone who wants it, but the headline should always answer "so what does this mean...

### Evaluation

**What it did well:** Constraining the format to exactly three points forced the most disciplined, prioritized answer of the three — each point is distinct (translate to business consequence, show confidence visually, pair the limitation with a path to resolution) rather than overlapping. Every point came with a concrete, fully worked example (an attribution/conversion-rate example, a churn dashboard with a shaded forecast band, and a customer survey coverage example), which makes this response the easiest to act on immediately — an analyst could almost lift the churn dashboard example directly into a slide.

**What was missing or generic:** By forcing only three points, some useful ideas from Strategy 1 were dropped entirely — there's no mention of avoiding false precision or maintaining consistency across reports over time. The examples, while concrete, are still hypothetical and generic (a churn dashboard, a customer survey) rather than tied to any specific audience or industry, so it lacks the boardroom specificity that Strategy 2's persona introduced.

---

## Conclusion

All three prompts converged on the same core idea — translate statistical uncertainty into business consequences rather than stating it in technical terms — but the prompting strategy changed how usable the answer was. The direct baseline prompt (Strategy 1) produced the most complete list of principles but was generic and unprioritized, leaving the reader to figure out what mattered most. The persona prompt (Strategy 2) produced the most sophisticated single idea (tie the limitation explicitly to what it does and doesn't change about the recommendation) and the most realistic, high-stakes examples, but it narrowed the guidance to one specific industry context and didn't fully sustain the persona's voice. The format-constrained prompt (Strategy 3) produced the most useful output for a BI analyst overall, because it combined a manageable, prioritized structure (exactly three points) with a concrete, board-ready example attached to each one, making it the most directly actionable for building an actual dashboard or slide. The strongest real-world prompt would likely combine Strategy 2's audience-specific persona with Strategy 3's format constraint, since specifying both who the analyst is talking to and how many points to return appears to do more to improve usefulness than either technique alone.
