import React, { useState, useEffect, useMemo, useRef } from 'react';
import { MessageCircle, X } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { API_BASE_URL } from '../config/constants';

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
  const sessionLinked = useRef(false);
  const linkInFlight = useRef(false);
  const sessionId = useMemo(() => getOrCreateSessionId(), []);

  const iframeSrc = useMemo(
    () => `${IFRAME_EMBED_URL}?sessionId=${encodeURIComponent(sessionId)}`,
    [sessionId]
  );

  const linkSession = async (retries = 2) => {
    if (sessionLinked.current || linkInFlight.current) return;
    const token = localStorage.getItem('customerToken');
    if (!token) return;

    linkInFlight.current = true;
    try {
      const res = await fetch(`${API_BASE_URL}/api/chatbot/link-session`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ session_id: sessionId }),
      });
      const data = await res.json().catch(() => ({}));
      // Any valid JSON HTTP response — do not retry (even when success is false).
      sessionLinked.current = true;
      if (data?.success) {
        console.log('[CHATBOT] link-session ok:', data.session_id, data.user_id);
      } else {
        console.warn('[CHATBOT] link-session rejected:', data?.error || res.status);
      }
      return;
    } catch (e) {
      console.warn('[CHATBOT] link-session network error, retries left:', retries - 1, e);
      if (retries > 1) {
        linkInFlight.current = false;
        setTimeout(() => linkSession(retries - 1), 3000);
        return;
      }
    } finally {
      linkInFlight.current = false;
    }
  };

  useEffect(() => {
    if (customerToken && isCustomer()) {
      linkSession();
    }
  }, [customerToken, isCustomer]);

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
