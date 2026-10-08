/**
 * Static Italian copy for "Chiedi a Mia" - the Decision Detail's own section (Gate 20) and, since
 * Home UI V1, the Home's property-level Mia (`miaHomeCopy` below). The visible assistant is Mia
 * (Home UI V1, D5); NINFA stays the name of the product, and every internal module/endpoint name
 * (`AskNinfaPanel`, `askNinfa`, `/ask`) is deliberately unchanged. Deliberately NOT a chatbot: no
 * provider/model mention anywhere, no "thinking"/"generating" language - see
 * `askNinfaCopy.submitting` for the one loading line this surface ever shows.
 */
export const askNinfaCopy = {
  heading: "Chiedi a Mia",
  supportingText: "Approfondisci questa decisione usando i dati che NINFA ha già analizzato.",

  suggestedQuestionsLabel: "Domande suggerite",
  suggestedQuestions: [
    "Perché NINFA mi sta mostrando questa decisione?",
    "Cosa significa questo scostamento?",
    "Cosa posso verificare?",
  ] as const,

  questionLabel: "La tua domanda",
  placeholder: "Fai una domanda su questa decisione",
  submit: "Chiedi a Mia",
  submitting: "Mia sta analizzando questa decisione…",

  answerHeading: "Risposta di Mia",
  limitationsHeading: "Da tenere presente",

  insufficientContextHeading:
    "Mia non ha abbastanza informazioni per rispondere con affidabilità a questa domanda.",
  insufficientContextSupporting:
    "Prova a formulare la domanda in modo diverso oppure consulta i dati disponibili nella decisione.",

  unavailableHeading: "Chiedi a Mia non è disponibile in questo momento.",
  unavailableSupporting: "Puoi riprovare manualmente.",

  refused: "Mia non può rispondere a questa domanda nel contesto della decisione.",

  networkError: "Non è stato possibile ottenere una risposta da Mia.",

  retry: "Riprova",
} as const;

/**
 * "Chiedi a Mia..." on the Home (Home UI V1): ONE question about TODAY'S analysis of the property -
 * never a conversation. The four suggested questions are the approved set; they only ever FILL the
 * input (the user confirms with Enter/submit), exactly like the Decision Detail's own chips. Each
 * is answerable from what the backend's Home context really contains (decisions already produced by
 * the engine, in NINFA's order, plus coverage and the factual last booking import) - none asks Mia
 * to find a problem on her own, to size a loss, or to judge whether data is "up to date".
 */
export const miaHomeCopy = {
  name: "Mia",
  formLabel: "Chiedi a Mia",
  inputLabel: "La tua domanda per Mia",
  placeholder: "Chiedi a Mia...",
  captionSuggestions: "Chiedi a Mia o scegli una domanda",
  suggestedQuestionsLabel: "Domande suggerite",
  suggestedQuestions: [
    "Ci sono altri problemi oltre a questo?",
    "Qual è la priorità più urgente oggi?",
    "Quale decisione ha l'impatto economico più alto?",
    "Quali dati ha usato NINFA oggi?",
  ] as const,
  submit: "Invia la domanda a Mia",
  submitting: "Mia sta analizzando la situazione di oggi…",
  yourQuestion: "La tua domanda",
  answerHeading: "Risposta di Mia",
  limitationsHeading: "Da tenere presente",
  insufficientContextHeading:
    "Mia non ha abbastanza informazioni per rispondere con affidabilità a questa domanda.",
  insufficientContextSupporting:
    "Prova a formulare la domanda in modo diverso oppure apri le decisioni di oggi per i dettagli.",
  unavailableHeading: "Mia non è disponibile in questo momento.",
  unavailableSupporting: "Puoi riprovare manualmente.",
  refused: "Mia non può rispondere a questa domanda.",
  networkError: "Non è stato possibile ottenere una risposta da Mia.",
  retry: "Riprova",
} as const;
