# Frozen applicability labels

The 32 labels and each case's applicability contract were authored before
running either policy on this set. They do not come from MiniLM, NLI, the
experimental extractor, or model judgments. The cases are stipulated technical
procedures: a valid request asks for the same action and material requirements;
an invalid request changes a required action, permission, destination, method,
server, or marker; an abstain request omits information needed to know whether
the specific cached answer applies. Two valid requests per family include
paraphrases and environment omissions explicitly harmless under the stipulated
answer. Ambiguous rows are not counted as invalid ground truth.

Question strings and families are disjoint from the inspected technical NLI
development set and the previous bidirectional lockbox. These controlled labels
are independent of the verifier but are not externally reviewed factual
documentation or production-traffic labels. This set cannot establish a
population incorrect-acceptance rate or factual truth of a cached answer.
