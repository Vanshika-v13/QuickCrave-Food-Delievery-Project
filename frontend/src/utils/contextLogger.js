const loggedWarnings = new Set();

export const logProviderWarning = (contextName) => {
  if (loggedWarnings.has(contextName)) return;

  console.error(
    `[CRITICAL][${contextName}] Missing Provider! \n` +
    `The component using use${contextName} is not wrapped in <${contextName}Provider />. \n` +
    `This will lead to silent failures and incorrect UI state.`
  );

  loggedWarnings.add(contextName);
};
