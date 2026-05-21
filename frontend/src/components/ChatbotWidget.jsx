import React, { useState, useEffect, useMemo } from 'react';
import { MessageCircle, X } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import apiClient from '../services/apiClient';

const SESSION_STORAGE_KEY = 'dialogflow_session_id';
const IFRAME_EMBED_URL =
  'https://console.dialogflow.com/api-client/demo/embedded/972b0ef9-d1df-4ae5-af60-04b1783caa76';

function getOrCreateSessionId() {
  let id = localStorage.getItem(SESSION_STORAGE_KEY);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(SESSION_STORAGE_KEY, id);
  }
  return id;
}

const ChatbotWidget = () => {
  const { customerToken, isCustomer, loading } = useAuth();
  const [open, setOpen] = useState(false);
  const sessionId = useMemo(() => getOrCreateSessionId(), []);

  const iframeSrc = useMemo(
    () => `${IFRAME_EMBED_URL}?sessionId=${encodeURIComponent(sessionId)}`,
    [sessionId]
  );

  const linkSession = async (retries = 3) => {
    const token = localStorage.getItem('customerToken');
    if (!token) return;
    const sid = localStorage.getItem('dialogflow_session_id') || sessionId;
    if (!sid) return;

    try {
      const res = await fetch(
        `${window.location.protocol}//${window.location.hostname}:8000/api/chatbot/link-session`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + token
          },
          body: JSON.stringify({ session_id: sid })
        }
      );
      const data = await res.json();
      console.log('[CHATBOT] link-session:', data);
    } catch (e) {
      console.warn('[CHATBOT] link-session failed, retries left:', retries - 1);
      if (retries > 1) {
        setTimeout(() => linkSession(retries - 1), 3000);
      }
    }
  };

  useEffect(() => { linkSession(); }, []);
  useEffect(() => { if (open) linkSession(); }, [open]);

  if (loading || !customerToken || !isCustomer()) {
    return null;
  }

  return (
    <div className="fixed bottom-6 right-6 z-[999]">
      {open && (
        <div
          className="fixed bottom-20 right-6 z-[998] flex h-96 w-80 flex-col overflow-hidden rounded-lg border border-gray-200 bg-white shadow-2xl"
          role="dialog"
          aria-label="QuickCrave chat assistant"
        >
          <iframe
            src={iframeSrc}
            title="Dialogflow assistant"
            className="h-full w-full flex-1 border-0"
            allow="clipboard-write; microphone"
          />
        </div>
      )}

      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex h-14 w-14 items-center justify-center rounded-full bg-orange-500 text-white shadow-lg transition hover:bg-orange-600 active:scale-95"
        aria-label={open ? 'Close chat' : 'Open chat'}
        aria-expanded={open}
      >
        {open ? <X className="h-6 w-6" /> : <MessageCircle className="h-6 w-6" />}
      </button>
    </div>
  );
};

export default ChatbotWidget;
