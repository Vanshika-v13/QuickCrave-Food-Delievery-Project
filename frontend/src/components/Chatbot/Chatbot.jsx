import React, { useEffect, useRef } from 'react';
import { useAuth } from '../../hooks/useAuth';
import apiClient from '../../services/apiClient';

const Chatbot = () => {
  const { customerUser, customerToken } = useAuth();
  const linkedRef = useRef(false);

  useEffect(() => {
    if (!customerToken || !customerUser?.id) return;

    const sessionId = `web-${customerUser.id}`;
    const messenger = document.querySelector('df-messenger');
    if (messenger) {
      messenger.setAttribute('session-id', sessionId);
      messenger.setAttribute('user-id', String(customerUser.id));
    }

    if (linkedRef.current) return;
    linkedRef.current = true;
    apiClient
      .post('/api/chatbot/link-session', { session_id: sessionId })
      .catch((err) => console.warn('[Chatbot] link-session failed', err));
  }, [customerToken, customerUser?.id]);

  useEffect(() => {
    const handleResponse = (event) => {
      try {
        const messages = event?.detail?.response?.queryResult?.fulfillmentMessages || [];
        const payloadMsg = messages.find((m) => m.payload);

        if (payloadMsg?.payload?.success) {
          const { orderId, total } = payloadMsg.payload;
          console.log(`[Chatbot] Order placed successfully. ID: ${orderId}`);
          window.dispatchEvent(
            new CustomEvent('chatbot-order-placed', { detail: { orderId, total } })
          );
        }
      } catch (err) {
        console.error('Error processing df-response', err);
      }
    };

    window.addEventListener('df-response-received', handleResponse);
    return () => window.removeEventListener('df-response-received', handleResponse);
  }, []);

  return (
    <df-messenger
      intent="WELCOME"
      chat-title="QuickCrave Bot"
      agent-id="972b0ef9-d1df-4ae5-af60-04b1783caa76"
      language-code="en"
    ></df-messenger>
  );
};

export default Chatbot;
