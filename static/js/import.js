/* global Vue */

// ChildNode.remove() polyfill for Internet Explorer
// from: https://github.com/jserz/js_piece/blob/master/DOM/ChildNode/remove()/remove().md
(function (arr) {
  arr.forEach(function (item) {
    item.remove = item.remove || function () {
      this.parentNode.removeChild(this);
    };
  });
})([Element.prototype, CharacterData.prototype, DocumentType.prototype]);

Vue.component("ProgressBar", {
  props: ['width'],
  template: '\
    <div class="progressbar">\
      <div class="progress" :style="{width: (width || 0) * 100 + \'%\'}"><div>\
   </div>'
});

Vue.component("ResultDisplay", {
  props: ['manifestUrl'],
  // TODO: Show spinner until manifest is loaded?
  template: '<div>TODO</div>',
  data: function() {
    return {
      manifest: null
    };
  },
  created: function() {
    var vm = this;
    axios.get(this.manifestUrl)
      .then(function(response) {
        vm.manifest = response.data;
      });
  },
  computed: {
    previewImage: function() {
      return this.manifest.thumbnail;
    },
    numberOfPages: function() {
      return this.manifest.sequences[0].canvases.length;
    },
    label: function() {
      return this.manifest.label;
    },
    viewerUrl: function() {
      return "/view/" + this.manifest['@id'].split('/').slice(-2)[0];
    }
  }
});

Vue.component("JobDisplay", {
  props: ['job'],
  data: function() {
    return {
      queueLength: this.job.position + 1
    };
  },
  template: '\
    <div class="import-status">\
      <template v-if="showProgressBar">\
        <ProgressBar v-if="completionRatio !== null"\
                     :width="completionRatio" />\
        <div class="job-status">{{ job.status }}</div>\
      </template>\
      <p v-else-if="showError" class="import-error">\
        {{ job.message }}\
        <a @click="triggerClose" class="close"/>\
      </p>\
      <result-display v-else :manifest-url="this.job.result" />\
    </div>',
  computed: {
    showProgressBar: function() {
      return (this.job.status === 'queued' || this.job.status === 'started');
    },
    showError: function() {
      return this.job.status === 'failed';
    },
    completionRatio: function() {
      if (this.job.status === 'queued') {
        return (this.queueLength - this.job.position + 1) / this.queueLength;
      } else if (this.job.status === 'started') {
        return this.job.current_image / this.job.total_images;
      } else {
        return null;
      }
    }
  },
  methods: {
    triggerClose: function() {
      this.$emit('dismiss-job', this.job.id);
    }
  }
});

Vue.component("NotificationForm", {
  props: ['jobIds'],
  data: function() {
    return {
      viewForm: false,
      recipient: '',
      wasSubmitted: false,
      errorMessage: null,
      invalid: false
    };
  },
  template: '\
    <form class="pure-form notification-form" @submit.prevent>\
      <fieldset>\
        <label v-if="!viewForm" for="notification-checkbox">\
          <input name="notification-checkbox" v-model="viewForm" \
                 type="checkbox" class="form-control"> \
                 Notify me via email\
        </label>\
        <template v-else-if="!wasSubmitted">\
          <input v-model="recipient" :class="{invalid: isDisabled}" type="email"\
                 name="recipient" @invalid="invalidate"\
                 @click="onClick" placeholder="Email" class="pure-form-control">\
          <button @click="registerForNotifications" :disabled="isDisabled" type="submit"\
                  class="pure-button pure-button-secondary">Submit</button>\
          <span v-if="isDisabled" class="error-message">{{ errorMessage }}</span>\
        </template>\
        <span v-else>\
          You will be notified at {{ recipient }} once the manifests are finished\
        </span>\
      <fieldset>\
    </form>',
  computed: {
    isDisabled: function() {
      return this.invalid || this.errorMessage !== null;
    }
  },
  methods: {
    invalidate: function() {
      this.invalid = true;
    },
    onClick: function() {
      this.errorMessage = null;
      this.invalid = false;
    },
    registerForNotifications: function() {
      var vm = this;
      axios.post('/api/status/notify', {recipient: this.recipient,
                                        jobs: this.jobIds})
        .then(function(resp) {
          vm.wasSubmitted = true;
        })
        .catch(function(err) {
          if (err.response) {
            vm.errorMessage = err.response.data.message;
          } else {
            console.error(err);
          }
        });
    }
  }
});


Vue.component("MetsForm", {
  props: ['jobIds'],
  data: function() {
    return {
      metsUrl: '',
      errorMessage: null,
      invalid: false
    };
  },
  template: '\
    <div class="pure-form mets-input">\
      <NotificationForm v-if="hasJobs" :jobIds="jobIds" />\
      <form @submit.prevent>\
        <fieldset>\
          <input v-model="metsUrl" type="url" class="form-control"\
                 @click="onClick" name="mets-url" @invalid="invalidate" \
                 placeholder="Put a METS URL in here!"\
                 :class="{invalid: isDisabled}">\
          <button @click="submitUrl" class="pure-button-primary pure-button"\
                  type="submit" :disabled="isDisabled" >\
            IIIF it!\
          </button>\
          <span v-if="isDisabled" class="error-message">{{ errorMessage }}</span>\
        </fieldset>\
      </form>\
    </div>',
  computed: {
    isDisabled: function() {
      return this.invalid || this.errorMessage !== null;
    },
    hasJobs: function() {
      return this.jobIds.size > 0;
    }
  },
  methods: {
    invalidate: function() {
      this.invalid = true;
    },
    onClick: function() {
      this.invalid = false;
      this.errorMessage = null;
    },
    submitUrl: function() {
      var vm = this;
      axios.post('/api/import', {url: this.metsUrl})
        .then(function(resp) {
          vm.errorMessage = null;
          vm.metsUrl = '';
          vm.$emit("new-job", resp.data);
        })
        .catch(function(err) {
          if (err.response) {
            vm.errorMessage = err.response.data.message;
          } else {
            console.error(err);
          }
        });
    }
  }
});


var app = new Vue({
  data: {
    jobIds: [],  // to store the order the jobs were added in
    jobs: {},
    streams: {}
  },
  template: '\
    <div class="mets-importer">\
      <MetsForm @new-job="onJobCreated" :jobIds="jobIds" />\
      <JobDisplay v-for="jobId in jobIds"\
                  :job="jobs[jobId]" @dismiss-job="onJobDismissed" />\
    </div>',
  methods: {
    onJobCreated: function(job) {
      this.jobIds.push(job.id);
      this.$set(this.jobs, job.id, job);
      var vm = this;
      var eventStream = new EventSource("/api/tasks/" + job.id + "/stream");
      eventStream.addEventListener('message', function(event) {
        vm.$set(vm.jobs, job.id, JSON.parse(event.data));
      });
      this.$set(this.streams, job.id, eventStream);
    },
    onJobDismissed: function(jobId) {
      this.jobIds.splice(this.jobIds.indexOf(jobId), 1);
      this.$delete(this.jobs, jobId);
    }
  }
});


app.$mount(".mets-importer");
