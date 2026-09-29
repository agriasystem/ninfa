/**
 * Static Italian copy for "Chiedi a NINFA" (Gate 20). Deliberately NOT a chatbot: no persona name
 * beyond "NINFA" itself, no provider/model mention anywhere, no "thinking"/"generating" language -
 * see `askNinfaCopy.submitting` for the one loading line this surface ever shows.
 */
export const askNinfaCopy = {
  heading: "Chiedi a NINFA",
  supportingText: "Approfondisci questa decisione usando i dati che NINFA ha già analizzato.",

  suggestedQuestionsLabel: "Domande suggerite",
  suggestedQuestions: [
    "Perché NINFA mi sta mostrando questa decisione?",
    "Cosa significa questo scostamento?",
    "Cosa posso verificare?",
  ] as const,

  questionLabel: "La tua domanda",
  placeholder: "Fai una domanda su questa decisione",
  submit: "Chiedi a NINFA",
  submitting: "NINFA sta analizzando questa decisione…",

  answerHeading: "Risposta NINFA",
  limitationsHeading: "Da tenere presente",

  insufficientContextHeading:
    "NINFA non ha abbastanza informazioni per rispondere con affidabilità a questa domanda.",
  insufficientContextSupporting:
    "Prova a formulare la domanda in modo diverso oppure consulta i dati disponibili nella decisione.",

  unavailableHeading: "Chiedi a NINFA non è disponibile in questo momento.",
  unavailableSupporting: "Puoi riprovare manualmente.",

  refused: "NINFA non può rispondere a questa domanda nel contesto della decisione.",

  networkError: "Non è stato possibile ottenere una risposta da NINFA.",

  retry: "Riprova",
} as const;
