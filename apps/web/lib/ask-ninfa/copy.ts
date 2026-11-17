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
 * "Chiedi a Mia..." on the Home (Home UI V1; a conversation since Mia OpenAI Intelligence V1). The four
 * suggested questions are the approved set; they only ever FILL the input (the user confirms with
 * Enter/submit), exactly like the Decision Detail's own chips. Each is answerable from what NINFA really
 * holds (decisions the engine already produced, in its order, plus coverage and the factual last
 * booking import) - none asks Mia to find a problem on her own, to size a loss, or to judge whether data
 * is "up to date". The wording of a reply (and the single dignified error) is shared with the panel of
 * the other pages (`miaPanelCopy` below).
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
  // Shown (and announced) while the one request in flight is running. Deliberately non-technical: it
  // never names a tool, a source or a model.
  submitting: "Mia sta analizzando…",
  // The assistant's own name above her reply; the sent question reads "Hai chiesto: ..." to a screen
  // reader (visually hidden - sighted users read it as the user's own message).
  assistantName: "Mia",
  askedPrefix: "Hai chiesto:",
  // The conversation (Mia OpenAI Intelligence V1): the newest exchanges of the person's conversation
  // (the server keeps it), and the way to start a new one.
  conversationLabel: "Conversazione con Mia",
  newConversation: "Nuova conversazione",
  limitationsHeading: "Da tenere presente",
  insufficientContextHeading:
    "Mia non ha abbastanza informazioni per rispondere con affidabilità a questa domanda.",
  insufficientContextSupporting:
    "Prova a formulare la domanda in modo diverso oppure apri le decisioni di oggi per i dettagli.",
  // One dignified line for EVERY failure to answer (the provider is down, a timeout, a network error):
  // the figures NINFA shows do not depend on Mia, and the screen says so.
  unavailableHeading: "Al momento non riesco a completare l'analisi con Mia.",
  unavailableSupporting: "I dati NINFA restano disponibili normalmente.",
  refused: "Mia non può rispondere a questa domanda.",
  retry: "Riprova",
} as const;

/**
 * Mia on every other page (Mia OpenAI Intelligence V1): a small launcher in the shell and a side panel
 * with the same conversation. The launcher is NOT called "Chiedi a Mia": the Decision Detail already has
 * its own section and button with that name, and two controls with one name read as one. The panel
 * shares the replies' wording (and the single dignified error) with the Home through `miaHomeCopy`.
 */
export const miaPanelCopy = {
  launcher: "Parla con Mia",
  launcherLabel: "Apri la conversazione con Mia",
  panelLabel: "Conversazione con Mia",
  title: "Mia",
  closeLabel: "Chiudi la conversazione con Mia",
  formLabel: "Scrivi a Mia",
  intro: "Chiedi a Mia di questa pagina, dei dati della struttura o di come funziona NINFA.",
  placeholder: "Chiedi a Mia...",
} as const;
