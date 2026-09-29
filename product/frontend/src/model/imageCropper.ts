type CropSelection = {
  startXPct: number;
  endXPct: number;
  startYPct: number;
  endYPct: number;
};

const clamp = (value: number, min: number, max: number): number => Math.min(max, Math.max(min, value));

const loadImage = (src: string): Promise<HTMLImageElement> => {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('Failed to load image for cropping'));
    img.src = src;
  });
};

const showCropDialog = (objectUrl: string, image: HTMLImageElement): Promise<CropSelection | null> => {
  return new Promise((resolve) => {
    let startXPct = 0;
    let endXPct = 100;
    let startYPct = 0;
    let endYPct = 100;

    const overlay = document.createElement('div');
    overlay.style.position = 'fixed';
    overlay.style.inset = '0';
    overlay.style.background = 'rgba(0, 0, 0, 0.55)';
    overlay.style.display = 'flex';
    overlay.style.alignItems = 'center';
    overlay.style.justifyContent = 'center';
    overlay.style.zIndex = '10000';

    const dialog = document.createElement('div');
    dialog.style.width = 'min(980px, 94vw)';
    dialog.style.maxHeight = '92vh';
    dialog.style.background = '#fff';
    dialog.style.borderRadius = '10px';
    dialog.style.padding = '14px';
    dialog.style.display = 'flex';
    dialog.style.flexDirection = 'column';
    dialog.style.gap = '10px';

    const title = document.createElement('div');
    title.textContent = 'Crop image';
    title.style.fontSize = '15px';
    title.style.fontWeight = '700';

    const body = document.createElement('div');
    body.style.display = 'grid';
    body.style.gridTemplateColumns = '1.3fr 1fr';
    body.style.gap = '12px';

    const sourcePanel = document.createElement('div');
    sourcePanel.style.border = '1px solid #ddd';
    sourcePanel.style.borderRadius = '8px';
    sourcePanel.style.padding = '10px';

    const sourceTitle = document.createElement('div');
    sourceTitle.textContent = 'Selection';
    sourceTitle.style.fontSize = '12px';
    sourceTitle.style.fontWeight = '700';
    sourceTitle.style.marginBottom = '8px';

    const sourceViewport = document.createElement('div');
    sourceViewport.style.position = 'relative';
    sourceViewport.style.width = '100%';
    sourceViewport.style.height = '460px';
    sourceViewport.style.border = '1px solid #eee';
    sourceViewport.style.background = '#f8f8f8';
    sourceViewport.style.overflow = 'hidden';

    const sourceImage = document.createElement('img');
    sourceImage.src = objectUrl;
    sourceImage.alt = 'Crop source';
    sourceImage.style.width = '100%';
    sourceImage.style.height = '100%';
    sourceImage.style.objectFit = 'contain';
    sourceImage.style.display = 'block';

    const cropBox = document.createElement('div');
    cropBox.style.position = 'absolute';
    cropBox.style.border = '2px solid #0077ff';
    cropBox.style.background = 'rgba(0, 119, 255, 0.15)';
    cropBox.style.pointerEvents = 'none';
    cropBox.style.boxSizing = 'border-box';

    sourceViewport.appendChild(sourceImage);
    sourceViewport.appendChild(cropBox);
    sourcePanel.appendChild(sourceTitle);
    sourcePanel.appendChild(sourceViewport);

    const controlsPanel = document.createElement('div');
    controlsPanel.style.display = 'flex';
    controlsPanel.style.flexDirection = 'column';
    controlsPanel.style.gap = '10px';
    controlsPanel.style.border = '1px solid #ddd';
    controlsPanel.style.borderRadius = '8px';
    controlsPanel.style.padding = '10px';

    const previewTitle = document.createElement('div');
    previewTitle.textContent = 'Live preview';
    previewTitle.style.fontSize = '12px';
    previewTitle.style.fontWeight = '700';

    const previewCanvas = document.createElement('canvas');
    previewCanvas.width = 320;
    previewCanvas.height = 220;
    previewCanvas.style.width = '100%';
    previewCanvas.style.maxWidth = '320px';
    previewCanvas.style.border = '1px solid #eee';
    previewCanvas.style.background = '#fafafa';

    const valuesText = document.createElement('div');
    valuesText.style.fontSize = '12px';
    valuesText.style.color = '#444';

    const createSliderRow = (labelText: string, input: HTMLInputElement, valueEl: HTMLSpanElement) => {
      const wrap = document.createElement('div');
      wrap.style.display = 'flex';
      wrap.style.flexDirection = 'column';
      wrap.style.gap = '4px';

      const row = document.createElement('div');
      row.style.display = 'flex';
      row.style.justifyContent = 'space-between';
      row.style.fontSize = '12px';

      const label = document.createElement('span');
      label.textContent = labelText;
      row.appendChild(label);
      row.appendChild(valueEl);

      wrap.appendChild(row);
      wrap.appendChild(input);
      return wrap;
    };

    const makeRange = (min: number, max: number, value: number): HTMLInputElement => {
      const input = document.createElement('input');
      input.type = 'range';
      input.min = String(min);
      input.max = String(max);
      input.step = '1';
      input.value = String(value);
      input.style.width = '100%';
      return input;
    };

    const startXInput = makeRange(0, 99, 0);
    const endXInput = makeRange(1, 100, 100);
    const startYInput = makeRange(0, 99, 0);
    const endYInput = makeRange(1, 100, 100);

    const startXValue = document.createElement('span');
    const endXValue = document.createElement('span');
    const startYValue = document.createElement('span');
    const endYValue = document.createElement('span');

    const updatePreview = () => {
      startXPct = clamp(Number(startXInput.value), 0, 99);
      endXPct = clamp(Number(endXInput.value), 1, 100);
      startYPct = clamp(Number(startYInput.value), 0, 99);
      endYPct = clamp(Number(endYInput.value), 1, 100);

      if (startXPct >= endXPct) {
        if (document.activeElement === startXInput) {
          endXPct = clamp(startXPct + 1, 1, 100);
          endXInput.value = String(endXPct);
        } else {
          startXPct = clamp(endXPct - 1, 0, 99);
          startXInput.value = String(startXPct);
        }
      }

      if (startYPct >= endYPct) {
        if (document.activeElement === startYInput) {
          endYPct = clamp(startYPct + 1, 1, 100);
          endYInput.value = String(endYPct);
        } else {
          startYPct = clamp(endYPct - 1, 0, 99);
          startYInput.value = String(startYPct);
        }
      }

      startXValue.textContent = `${startXPct}%`;
      endXValue.textContent = `${endXPct}%`;
      startYValue.textContent = `${startYPct}%`;
      endYValue.textContent = `${endYPct}%`;

      const cropLeft = `${startXPct}%`;
      const cropTop = `${startYPct}%`;
      const cropWidth = `${endXPct - startXPct}%`;
      const cropHeight = `${endYPct - startYPct}%`;

      cropBox.style.left = cropLeft;
      cropBox.style.top = cropTop;
      cropBox.style.width = cropWidth;
      cropBox.style.height = cropHeight;

      const sx = Math.round((startXPct / 100) * image.naturalWidth);
      const sy = Math.round((startYPct / 100) * image.naturalHeight);
      const sw = Math.max(1, Math.round(((endXPct - startXPct) / 100) * image.naturalWidth));
      const sh = Math.max(1, Math.round(((endYPct - startYPct) / 100) * image.naturalHeight));

      valuesText.textContent = `x: ${sx}px → ${sx + sw}px | y: ${sy}px → ${sy + sh}px | ${sw}×${sh}px`;

      const ctx = previewCanvas.getContext('2d');
      if (!ctx) return;

      ctx.clearRect(0, 0, previewCanvas.width, previewCanvas.height);
      const scale = Math.min(previewCanvas.width / sw, previewCanvas.height / sh);
      const drawW = sw * scale;
      const drawH = sh * scale;
      const drawX = (previewCanvas.width - drawW) / 2;
      const drawY = (previewCanvas.height - drawH) / 2;

      ctx.drawImage(image, sx, sy, sw, sh, drawX, drawY, drawW, drawH);
    };

    startXInput.oninput = updatePreview;
    endXInput.oninput = updatePreview;
    startYInput.oninput = updatePreview;
    endYInput.oninput = updatePreview;

    controlsPanel.appendChild(previewTitle);
    controlsPanel.appendChild(previewCanvas);
    controlsPanel.appendChild(valuesText);
    controlsPanel.appendChild(createSliderRow('Start X', startXInput, startXValue));
    controlsPanel.appendChild(createSliderRow('End X', endXInput, endXValue));
    controlsPanel.appendChild(createSliderRow('Start Y', startYInput, startYValue));
    controlsPanel.appendChild(createSliderRow('End Y', endYInput, endYValue));

    body.appendChild(sourcePanel);
    body.appendChild(controlsPanel);

    const footer = document.createElement('div');
    footer.style.display = 'flex';
    footer.style.justifyContent = 'flex-end';
    footer.style.gap = '8px';

    const makeButton = (label: string) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = label;
      button.style.padding = '7px 12px';
      button.style.fontSize = '12px';
      button.style.cursor = 'pointer';
      return button;
    };

    const cancelButton = makeButton('Cancel');
    const applyButton = makeButton('Apply crop');

    const cleanup = () => {
      document.removeEventListener('keydown', onEsc);
      overlay.remove();
    };

    const closeWith = (result: CropSelection | null) => {
      cleanup();
      resolve(result);
    };

    const onEsc = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        closeWith(null);
      }
    };

    document.addEventListener('keydown', onEsc);

    overlay.onclick = (event: MouseEvent) => {
      if (event.target === overlay) {
        closeWith(null);
      }
    };

    cancelButton.onclick = () => closeWith(null);
    applyButton.onclick = () => closeWith({ startXPct, endXPct, startYPct, endYPct });

    footer.appendChild(cancelButton);
    footer.appendChild(applyButton);

    dialog.appendChild(title);
    dialog.appendChild(body);
    dialog.appendChild(footer);
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);

    updatePreview();
  });
};

export const cropImageBeforeInsertWithSliders = async (file: File): Promise<File> => {
  if (!file.type.startsWith('image/')) {
    return file;
  }

  const objectUrl = URL.createObjectURL(file);

  try {
    const image = await loadImage(objectUrl);
    const crop = await showCropDialog(objectUrl, image);

    if (!crop) {
      return file;
    }

    const sx = Math.round((crop.startXPct / 100) * image.naturalWidth);
    const sy = Math.round((crop.startYPct / 100) * image.naturalHeight);
    const swRaw = Math.max(1, Math.round(((crop.endXPct - crop.startXPct) / 100) * image.naturalWidth));
    const shRaw = Math.max(1, Math.round(((crop.endYPct - crop.startYPct) / 100) * image.naturalHeight));
    const sw = Math.max(1, Math.min(swRaw, image.naturalWidth - sx));
    const sh = Math.max(1, Math.min(shRaw, image.naturalHeight - sy));

    const canvas = document.createElement('canvas');
    canvas.width = sw;
    canvas.height = sh;

    const ctx = canvas.getContext('2d');
    if (!ctx) {
      return file;
    }

    ctx.drawImage(image, sx, sy, sw, sh, 0, 0, sw, sh);

    const croppedBlob = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob(resolve, file.type || 'image/png');
    });

    if (!croppedBlob) {
      return file;
    }

    return new File([croppedBlob], file.name, {
      type: croppedBlob.type || file.type,
      lastModified: Date.now()
    });
  } catch (error) {
    console.error('Failed to crop image before upload', error);
    alert('Failed to crop image. Using original image.');
    return file;
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
};
